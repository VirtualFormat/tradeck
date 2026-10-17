"""叠加策略（composite）合并器 — 选股与回测共用的纯函数。

为什么单独成模块：选股（loader 闭包 + screener）和回测（runner → matcher）
都要合并子策略信号，必须共享同一套口径，否则会出现「选股与回测使用不同
逻辑」的金融错误。参照 tick-stock-panel strategy/composite.py 的合并语义。

两种合并入口：
- merge_signal_matrices：回测合并。输入各子 StrategySignals，输出合并 StrategySignals。
- merge_screen_results：选股合并。输入各子 (入选 symbol 集, {symbol: score})，输出合并。

合并语义：
- entry：union=OR(entries)；intersect=Σ(entries) >= min_confirm
- score：各子内部按 score 降序排名归一到 [0,1]，命中子策略间按权重加权。
         排名是相对位置，跨子策略天然可比，不依赖各子 per-strategy 的量纲。
- exit（回测）：来源投影。每个子策略 i 的 exit 仅在它自己 entry 后的持仓窗口内生效，
              避免「B 的退出信号平掉 A 的仓位」（幽灵平仓）。窗口由全局 max_hold 封顶。

退出投影的金融正确性：撮合引擎（engine/matcher.py）读全局 signals.exit，不区分来源。
若直接 OR(exit) 会产生幽灵平仓（B 把 A 选的仓位卖掉）。来源投影在合并器（撮合前）
解决，撮合层零改动。
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from app.strategy.base import StrategySignals, empty_signals

# 中性分：子策略无 score、单候选（无法排名）或非有限 score 时的占位，不污染融合结果。
_NEUTRAL_NORM = 0.5

# 子策略上限：超出在加载期拒绝（loader），合并器兜底，防信号计算成本/OOM 爆炸。
MAX_COMPOSITE_CHILDREN = 8

# 退出投影窗口的成交滞后余量（交易日）：entry 信号到实际买入在 open_t+1 口径下
# 滞后 1 日，涨跌停/T+1/分钟不确认顺延再加 1 日。投影窗口按 entry 日起算时须补
# 这段滞后，否则会把落在「实际买入日+max_hold」内的 exit 误滤掉（review P1）。
_ENTRY_FILL_LAG_BARS = 2


@dataclass
class CompositeChildResult:
    """单个子策略的选股截面结果（供选股合并）。"""
    symbols: set[str] = field(default_factory=set)
    scores: dict[str, float] = field(default_factory=dict)


def _effective_weights(
    children_weights: list[float],
    hits_mask: list[bool],
) -> tuple[list[float], float]:
    """从权重列表中筛出命中子策略的权重，返回 (命中权重列表, 命中权重总和)。"""
    effective = [w for w, hit in zip(children_weights, hits_mask, strict=True) if hit]
    total = sum(effective)
    return effective, total


def merge_screen_results(
    results: list[CompositeChildResult],
    children_weights: list[float],
    merge_mode: str,
    min_confirm: int,
) -> dict[str, float]:
    """选股合并：按 symbol 聚合各子结果，标准化排名加权融合 score。

    Args:
        results: 各子策略的选股结果（顺序与 children_weights 对齐）
        children_weights: 各子权重（顺序对齐）
        merge_mode: "union"（任一命中即入选） | "intersect"（至少 min_confirm 个命中）
        min_confirm: intersect 模式下命中的最少子策略数；<=0 视为全部子策略

    Returns:
        {symbol: 融合 score（0-100）}，排序交给调用方（screener 按分数降序截 limit）。
    """
    n_children = len(results)
    if n_children == 0:
        return {}

    # 各子的 symbol → 排名归一 score。排名基于子策略内部的原始 score 降序。
    # norm∈[0,1]，最优标的=1。单候选或无 score 时用中性分。
    per_child_norm: list[dict[str, float]] = []
    for res in results:
        norm: dict[str, float] = {}
        scored = {s: v for s, v in res.scores.items() if s in res.symbols}
        if scored:
            ordered = sorted(scored, key=lambda s: scored[s], reverse=True)
            count = len(ordered)
            for rank, sym in enumerate(ordered, start=1):
                # 单候选无法排名，必须用中性分：当成「最优=1」会凭空抬高融合分，
                # 而回测合并（merge_signal_matrices 的 n <= 1 分支）用的是中性分，
                # 两条路径同一天同一标的会给出不同评分与排序。
                norm[sym] = (
                    _NEUTRAL_NORM if count <= 1 else 1 - (rank - 1) / (count - 1)
                )
        # 入选但无 score 的标的：命中即中性分，不奖励也不惩罚。
        for sym in res.symbols:
            if sym not in norm:
                norm[sym] = _NEUTRAL_NORM
        per_child_norm.append(norm)

    # 入围标的集合（各子入选的并集）
    universe: set[str] = set()
    for res in results:
        universe.update(res.symbols)

    effective_min = max(min_confirm, 1) if min_confirm and min_confirm > 0 else n_children
    scores: dict[str, float] = {}
    for sym in universe:
        hits = [i for i in range(n_children) if sym in per_child_norm[i]]
        if not hits:
            continue
        if merge_mode == "intersect" and len(hits) < effective_min:
            continue
        weights, total_w = _effective_weights(
            children_weights, [i in hits for i in range(n_children)]
        )
        if total_w <= 0:
            # 全部权重为 0：退化为均等。
            total_w = float(len(hits))
            weights = [1.0] * len(hits)
        blended = sum(
            w * per_child_norm[i][sym] for i, w in zip(hits, weights, strict=True)
        )
        scores[sym] = round(blended / total_w * 100, 4)
    return scores


def _hold_masks_from_entries(entries: list[np.ndarray], max_hold: int) -> list[np.ndarray]:
    """计算每个子策略的持仓窗口掩码。

    hold_mask_i[t, a] = True 当且仅当存在 t' <= t 使 entry_i[t', a] 触发且仍在
    投影窗口内。窗口长度 = max_hold + 成交滞后余量（entry→实际买入在 open_t+1/
    涨跌停顺延下有 1~2 个交易日滞后；若只按 entry 日起算 max_hold，会把落在
    「实际买入日 + max_hold」内但「entry 日 + max_hold」外的 exit 误滤掉——
    review P1 指出后加余量对齐参照意图与撮合实际）。
    实现用前向填充：从每个 entry 起向前扩展 max_hold-1 个 bar 为 True。
    """
    if max_hold <= 0:
        max_hold = 1
    else:
        # 成交滞后余量（review P1）：entry→实际买入在 open_t+1/涨跌停顺延后约 1~2 日。
        # 窗口过紧会把「实际买入日+max_hold」内但「entry 日+max_hold」外的 exit 误滤掉。
        max_hold = max_hold + _ENTRY_FILL_LAG_BARS
    masks: list[np.ndarray] = []
    for entry in entries:
        raw = entry.astype(bool, copy=False)
        # 对每个 asset 列，把 True 向前传播 max_hold 个 bar。
        # 用按行位移 OR 实现：mask[t] |= raw[t-k] for k in [0, max_hold-1]
        mask = np.zeros_like(raw)
        window = raw.copy()
        mask |= window
        for _k in range(1, max_hold):
            window = np.roll(window, 1, axis=0)
            window[0, :] = False  # roll 会在顶部环绕，置零防未来泄漏
            mask |= window
        masks.append(mask)
    return masks


def merge_signal_matrices(
    sigs: list[StrategySignals],
    children_weights: list[float],
    merge_mode: str,
    min_confirm: int,
    max_hold: int,
    shape: tuple[int, int],
) -> StrategySignals:
    """回测合并：产出合并 entry/exit/score 矩阵。

    Args:
        sigs: 各子策略 StrategySignals（顺序与 children_weights 对齐）
        children_weights: 各子权重
        merge_mode / min_confirm: 同 merge_screen_results
        max_hold: 全局最长持仓天数，用于退出投影窗口封顶（<=0 时不封顶）
        shape: (n_times, n_assets)，子信号形状不符者已由调用方剔除

    Returns:
        合并后的 StrategySignals（entry_ref/exit_ref 不融合，分钟口径走 VWAP 降级）。
    """
    n_children = len(sigs)
    if n_children == 0 or n_children > MAX_COMPOSITE_CHILDREN:
        # 空或超限（loader 应已拦截，此处兜底）→ 空信号降级，绝不崩调用方。
        return empty_signals(shape)

    # ── entry ──
    entries = [np.asarray(s.entry, dtype=bool) for s in sigs]
    entry_stack = np.stack(entries, axis=0)  # (n_children, n_times, n_assets)
    if merge_mode == "intersect":
        effective_min = max(min_confirm, 1) if min_confirm and min_confirm > 0 else n_children
        confirm_count = entry_stack.sum(axis=0)  # (n_times, n_assets)
        merged_entry = confirm_count >= effective_min
    else:  # union
        merged_entry = entry_stack.any(axis=0)

    # ── exit 来源投影 ──
    # 每个子策略的 exit 仅在自己持仓窗口内生效，不串平其他子的仓位。
    # max_hold <= 0 表示不限持仓期 → 窗口扩展到序列末尾（n_times 行）。
    n_times = shape[0]
    window = max_hold if max_hold and max_hold > 0 else n_times
    hold_masks = _hold_masks_from_entries(entries, window)
    merged_exit = np.zeros(shape, dtype=bool)
    for i, s in enumerate(sigs):
        child_exit = np.asarray(s.exit, dtype=bool)
        merged_exit |= child_exit & hold_masks[i]

    # ── score 标准化排名加权 ──
    # 对每个 (time, asset)，在命中的子策略间按权重加权各自的内部排名归一值。
    weights = np.asarray(children_weights, dtype=np.float64)
    n_assets = shape[1]
    # 预计算每个子策略、每个 time 上 asset 的排名归一。
    norm_scores = np.zeros((n_children, n_times, n_assets), dtype=np.float64)
    for i, s in enumerate(sigs):
        raw = np.asarray(s.score, dtype=np.float64)
        for t in range(n_times):
            hit = entries[i][t]
            if not hit.any():
                continue
            hit_idx = np.flatnonzero(hit)
            hit_vals = raw[t][hit_idx]
            finite = np.isfinite(hit_vals)
            if not finite.any():
                norm_scores[i, t, hit_idx] = _NEUTRAL_NORM
                continue
            valid_idx = hit_idx[finite]
            valid_vals = hit_vals[finite]
            n = len(valid_idx)
            if n <= 1:
                norm_scores[i, t, valid_idx] = _NEUTRAL_NORM
                continue
            # 降序排名：最优=1，最差=0。
            order = np.argsort(-valid_vals, kind="stable")
            ranks = np.empty(n, dtype=np.float64)
            ranks[order] = np.arange(1, n + 1, dtype=np.float64)
            normalized = 1 - (ranks - 1) / (n - 1)
            norm_scores[i, t, valid_idx] = normalized

    hit_mask = entry_stack  # (n_children, n_times, n_assets)
    hit_weights = np.where(hit_mask, weights.reshape(-1, 1, 1), 0.0)
    weight_sum = hit_weights.sum(axis=0)  # (n_times, n_assets)
    blended = (norm_scores * hit_weights).sum(axis=0)
    safe_sum = np.where(weight_sum > 0, weight_sum, 1.0)
    merged_score = np.where(merged_entry, blended / safe_sum * 100, np.nan)
    merged_score = np.nan_to_num(merged_score, nan=np.nan, posinf=np.nan, neginf=np.nan)

    return StrategySignals(
        entry=merged_entry,
        exit=merged_exit,
        score=merged_score,
        # entry_ref/exit_ref 跨策略不可融合（量纲/语义各异），不输出参考线：
        # 分钟成交路径自动降级 VWAP 口径（matcher 对 None 参考线的既有处理）。
    )
