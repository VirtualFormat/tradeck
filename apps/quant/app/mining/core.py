"""因子挖掘核心算法 — RankIC / 相关性去重 / beam 组合搜索 / 嵌套样本外 / 晋级门槛。

设计对齐参照 mining.py，但按 tradeck 的矩阵结构（dates × symbols numpy）重写，
不依赖 polars panel。纯算法层：不碰数据加载/持久化/HTTP（那些在 runtime）。

时点红线（铁律）：
- forward return 用「未来收益」只能出现在「用 T 日因子预测 T+1..T+h 收益」的标签位，
  因子值本身绝不含未来数据（factors.py 已保证）。
- 嵌套样本外：每个 outer 测试折的数据绝不参与该折的因子选择/组合搜索（防过拟合）。
- 候选永不自动上线：evaluate_gate 只出「是否达晋级门槛」，发布动作在 runtime 由用户显式确认。
"""
from __future__ import annotations

import itertools
import logging
from dataclasses import dataclass, field

import numpy as np

logger = logging.getLogger(__name__)

# 晋级门槛（对齐参照 evaluate_candidate_gate 的证据阈值）
GATE_MIN_VALID_FOLDS = 2
GATE_MIN_POSITIVE_FOLD_RATIO = 2.0 / 3.0
GATE_MIN_OOS_SHARPE = 0.5
GATE_MAX_DRAWDOWN = -0.25
GATE_MIN_TRADES = 60


# ---------------------------------------------------------------------------
# Rank IC（截面因子与未来收益的 Spearman 相关）
# ---------------------------------------------------------------------------


def _rank(arr: np.ndarray) -> np.ndarray:
    """一维数组的秩（平均秩处理并列），NaN 保持 NaN。"""
    out = np.full(arr.shape, np.nan)
    valid = ~np.isnan(arr)
    if valid.sum() < 2:
        return out
    order = np.argsort(arr[valid], kind="mergesort")
    ranks = np.empty(valid.sum())
    ranks[order] = np.arange(valid.sum())
    # 并列给平均秩
    sorted_vals = arr[valid][order]
    i = 0
    while i < len(sorted_vals):
        j = i
        while j + 1 < len(sorted_vals) and sorted_vals[j + 1] == sorted_vals[i]:
            j += 1
        ranks[i : j + 1] = ranks[i : j + 1].mean()
        i = j + 1
    out[valid] = ranks
    return out


def _spearman(x: np.ndarray, y: np.ndarray) -> float:
    """两向量的 Spearman 相关（NaN 成对剔除）。"""
    mask = ~(np.isnan(x) | np.isnan(y))
    if mask.sum() < 3:
        return np.nan
    rx, ry = _rank(x[mask]), _rank(y[mask])
    if np.isnan(rx).any() or np.isnan(ry).any():
        return np.nan
    sx, sy = rx.std(), ry.std()
    if sx == 0 or sy == 0:
        return np.nan
    return float(np.mean((rx - rx.mean()) * (ry - ry.mean())) / (sx * sy))


def forward_returns(close: np.ndarray, horizon: int) -> np.ndarray:
    """未来 horizon 日收益（小数）：close[t+h]/close[t]-1，末尾 h 行与跨停牌 NaN。"""
    out = np.full(close.shape, np.nan)
    if close.shape[0] > horizon:
        future = np.full(close.shape, np.nan)
        future[:-horizon] = close[horizon:]
        out = np.where(
            np.isnan(close) | np.isnan(future), np.nan, future / close - 1.0
        )
    return out


def factor_rank_ic(
    factor: np.ndarray, fwd_ret: np.ndarray
) -> tuple[float, float, int]:
    """单因子 RankIC：逐日截面 Spearman(因子, 未来收益)，返回 (IC均值, ICIR, 有效天数)。

    ICIR = IC均值 / IC标准差（稳定性），天数太少返回 NaN。
    """
    ics = []
    for t in range(factor.shape[0]):
        ic = _spearman(factor[t], fwd_ret[t])
        if not np.isnan(ic):
            ics.append(ic)
    if len(ics) < 5:
        return np.nan, np.nan, len(ics)
    arr = np.array(ics)
    ic_mean = float(arr.mean())
    ic_std = float(arr.std())
    icir = ic_mean / ic_std if ic_std > 0 else 0.0
    return ic_mean, icir, len(ics)


# ---------------------------------------------------------------------------
# 因子相关性与去重
# ---------------------------------------------------------------------------


def factor_correlation(factors: dict[str, np.ndarray]) -> dict[tuple[str, str], float]:
    """全部因子对的平均逐日截面 Rank 相关（用于去重）。"""
    names = list(factors)
    result: dict[tuple[str, str], float] = {}
    for a, b in itertools.combinations(names, 2):
        fa, fb = factors[a], factors[b]
        cors = []
        for t in range(fa.shape[0]):
            c = _spearman(fa[t], fb[t])
            if not np.isnan(c):
                cors.append(c)
        result[(a, b)] = float(np.mean(cors)) if cors else 0.0
    return result


def prune_correlated(
    ics: dict[str, float],
    correlation: dict[tuple[str, str], float],
    threshold: float = 0.7,
) -> tuple[list[str], list[tuple[str, str]]]:
    """按 |IC| 降序贪心去重：保留强者，剔除与其相关超阈值的弱者。

    返回 (保留因子, [(被剔除, 剔除者)])。
    """
    order = sorted(ics, key=lambda n: abs(ics.get(n) or 0), reverse=True)
    kept: list[str] = []
    dropped: list[tuple[str, str]] = []
    for name in order:
        conflict = next(
            (k for k in kept
             if abs(correlation.get((k, name), correlation.get((name, k), 0.0))) > threshold),
            None,
        )
        if conflict is None:
            kept.append(name)
        else:
            dropped.append((name, conflict))
    return kept, dropped


# ---------------------------------------------------------------------------
# beam 组合搜索
# ---------------------------------------------------------------------------


def combine_factors(
    factors: dict[str, np.ndarray],
    names: tuple[str, ...],
    directions: dict[str, int],
) -> np.ndarray:
    """等权合成多因子（按方向调整符号后取截面 z-score 均值）。

    directions: {因子名: 1 或 -1}（由训练折 IC 符号决定，正向因子原样、反向取负）。
    """
    acc = None
    for n in names:
        f = factors[n] * directions[n]
        z = _cross_sectional_zscore(f)
        acc = z if acc is None else acc + z
    return acc / len(names) if acc is not None else np.full_like(factors[names[0]], np.nan)


def _cross_sectional_zscore(factor: np.ndarray) -> np.ndarray:
    """逐日截面 z-score（NaN 传播）。"""
    out = np.full(factor.shape, np.nan)
    for t in range(factor.shape[0]):
        row = factor[t]
        valid = ~np.isnan(row)
        if valid.sum() >= 2:
            mu, sd = row[valid].mean(), row[valid].std()
            if sd > 0:
                out[t, valid] = (row[valid] - mu) / sd
    return out


def beam_search(
    factors: dict[str, np.ndarray],
    fwd_ret: np.ndarray,
    ics: dict[str, float],
    directions: dict[str, int],
    max_size: int = 4,
    beam_width: int = 16,
    correlation: dict[tuple[str, str], float] | None = None,
    corr_threshold: float = 0.7,
) -> list[tuple[tuple[str, ...], float]]:
    """beam 搜索 ≤max_size 因子组合，按组合 |IC| 排序返回 [(组合, IC)]。

    每层只在上一层的 beam_width 个最优组合上扩展一个因子（控搜索预算）；
    同层剪枝与已选因子高相关（>corr_threshold）的候选。
    """
    candidates = [n for n in ics if not np.isnan(ics.get(n, np.nan))]
    # 第一层：单因子
    beam = [((n,), abs(ics[n])) for n in candidates]
    beam.sort(key=lambda x: x[1], reverse=True)
    beam = beam[:beam_width]
    best = list(beam)
    for size in range(2, max_size + 1):
        next_beam: list[tuple[tuple[str, ...], float]] = []
        for combo, _ in beam:
            for n in candidates:
                if n in combo:
                    continue
                if correlation is not None and any(
                    abs(correlation.get((c, n), correlation.get((n, c), 0.0))) > corr_threshold
                    for c in combo
                ):
                    continue
                new_combo = tuple(sorted(combo + (n,)))
                combined = combine_factors(factors, new_combo, directions)
                ic, _, _ = factor_rank_ic(combined, fwd_ret)
                if not np.isnan(ic):
                    next_beam.append((new_combo, abs(ic)))
        # 去重 + 排序 + 截断
        seen = set()
        dedup = []
        for combo, ic in sorted(next_beam, key=lambda x: x[1], reverse=True):
            if combo not in seen:
                seen.add(combo)
                dedup.append((combo, ic))
        if not dedup:
            break
        beam = dedup[:beam_width]
        best.extend(beam)
    # 全局去重排序
    seen = set()
    out = []
    for combo, ic in sorted(best, key=lambda x: x[1], reverse=True):
        if combo not in seen:
            seen.add(combo)
            out.append((combo, ic))
    return out


# ---------------------------------------------------------------------------
# 嵌套样本外验证
# ---------------------------------------------------------------------------


@dataclass
class OuterFold:
    """一个外层验证折：训练段选因子/定组合，测试段独立评估。"""

    train_start: int
    train_end: int   # 训练段 [train_start, train_end)
    test_start: int
    test_end: int    # 测试段 [test_start, test_end)


def make_nested_folds(
    n_days: int, n_outer: int = 3, train_ratio: float = 0.6
) -> list[OuterFold]:
    """把 n_days 切成 n_outer 个滚动外层折（训练窗在前、测试窗在后，不重叠）。

    train_ratio 为每折内训练段占比。天数太少返回空（调用方降级）。
    """
    if n_days < 40 or n_outer < 1:
        return []
    fold_len = n_days // n_outer
    folds = []
    for k in range(n_outer):
        start = k * fold_len
        end = n_days if k == n_outer - 1 else (k + 1) * fold_len
        seg = end - start
        train_len = int(seg * train_ratio)
        if train_len < 20 or seg - train_len < 5:
            continue
        folds.append(OuterFold(
            train_start=start, train_end=start + train_len,
            test_start=start + train_len, test_end=end,
        ))
    return folds


@dataclass
class FoldResult:
    """单折样本外结果。"""

    fold_index: int
    combo: tuple[str, ...]
    oos_sharpe: float
    oos_return: float
    oos_max_drawdown: float
    oos_trades: int
    oos_positive: bool


@dataclass
class CandidateResult:
    """一个候选组合的嵌套样本外评估汇总。"""

    combo: tuple[str, ...]
    directions: dict[str, int]
    folds: list[FoldResult] = field(default_factory=list)

    @property
    def valid_folds(self) -> int:
        return len(self.folds)

    @property
    def positive_fold_ratio(self) -> float:
        return sum(1 for f in self.folds if f.oos_positive) / len(self.folds) if self.folds else 0.0

    @property
    def oos_sharpe(self) -> float:
        vals = [f.oos_sharpe for f in self.folds if not np.isnan(f.oos_sharpe)]
        return float(np.mean(vals)) if vals else np.nan

    @property
    def oos_max_drawdown(self) -> float:
        vals = [f.oos_max_drawdown for f in self.folds]
        return float(min(vals)) if vals else np.nan

    @property
    def oos_trades(self) -> int:
        return sum(f.oos_trades for f in self.folds)


def evaluate_gate(c: CandidateResult) -> tuple[bool, list[str]]:
    """晋级门槛（对齐参照 evaluate_candidate_gate）：返回 (是否达标, 未达标原因)。"""
    reasons = []
    if c.valid_folds < GATE_MIN_VALID_FOLDS:
        reasons.append(f"有效外层折不足 {GATE_MIN_VALID_FOLDS}（{c.valid_folds}）")
    if c.positive_fold_ratio < GATE_MIN_POSITIVE_FOLD_RATIO:
        reasons.append(f"正收益折占比不足 {GATE_MIN_POSITIVE_FOLD_RATIO:.0%}（{c.positive_fold_ratio:.0%}）")
    if np.isnan(c.oos_sharpe) or c.oos_sharpe < GATE_MIN_OOS_SHARPE:
        reasons.append(f"样本外夏普不足 {GATE_MIN_OOS_SHARPE}（{c.oos_sharpe:.2f}）")
    if np.isnan(c.oos_max_drawdown) or c.oos_max_drawdown < GATE_MAX_DRAWDOWN:
        reasons.append(f"样本外最大回撤超 {abs(GATE_MAX_DRAWDOWN):.0%}（{c.oos_max_drawdown:.0%}）")
    if c.oos_trades < GATE_MIN_TRADES:
        reasons.append(f"样本外交易数不足 {GATE_MIN_TRADES}（{c.oos_trades}）")
    return (not reasons, reasons)
