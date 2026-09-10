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


def factor_daily_ics(factor: np.ndarray, fwd_ret: np.ndarray) -> list[float]:
    """逐日截面 Spearman(因子, 未来收益) 的 IC 序列（NaN 剔除）。"""
    ics = []
    for t in range(factor.shape[0]):
        ic = _spearman(factor[t], fwd_ret[t])
        if not np.isnan(ic):
            ics.append(ic)
    return ics


def factor_rank_ic(
    factor: np.ndarray, fwd_ret: np.ndarray
) -> tuple[float, float, int]:
    """单因子 RankIC：返回 (IC均值, ICIR, 有效天数)。

    ICIR = IC均值 / IC标准差（稳定性），天数太少返回 NaN。
    """
    ics = factor_daily_ics(factor, fwd_ret)
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
# 嵌套样本外验证（purge/embargo 防泄漏 + 真嵌套内外折）
# ---------------------------------------------------------------------------


@dataclass
class NestedValidationConfig:
    """嵌套验证折参数（所有单位均为交易日 bar 数，不是日历天数）。

    purge_bars：训练段与测试段之间的隔离带——剔除尾部训练样本，使其 forward
    return 窗口（horizon 日）不跨入测试段；embargo_bars：测试段之后的禁区，
    滚动到下一折时其起始训练样本的标签不会回看本折测试段。
    默认对齐参照 NestedValidationConfig（purge=30 >= 默认 horizon 5）。
    """

    outer_train_bars: int = 504
    outer_test_bars: int = 126
    outer_step_bars: int = 63
    inner_train_bars: int = 252
    inner_test_bars: int = 63
    inner_step_bars: int = 63
    purge_bars: int = 30
    embargo_bars: int = 5
    min_train_bars: int = 126

    def __post_init__(self) -> None:
        positive = {
            "outer_train_bars": self.outer_train_bars,
            "outer_test_bars": self.outer_test_bars,
            "outer_step_bars": self.outer_step_bars,
            "inner_train_bars": self.inner_train_bars,
            "inner_test_bars": self.inner_test_bars,
            "inner_step_bars": self.inner_step_bars,
            "min_train_bars": self.min_train_bars,
        }
        invalid = [name for name, value in positive.items() if value <= 0]
        if invalid:
            raise ValueError(f"嵌套验证 bar 数必须为正：{invalid}")
        if self.purge_bars < 0 or self.embargo_bars < 0:
            raise ValueError("purge_bars 与 embargo_bars 不能为负")


@dataclass
class ValidationFold:
    """一个验证折（外层或内层）：[train_start, train_end) 训练、purge 隔离、
    [test_start, test_end) 测试、embargo 禁区。全部为交易日下标半开区间。"""

    level: str          # "outer" / "inner"
    outer_index: int
    inner_index: int | None
    train_start: int
    train_end: int
    test_start: int
    test_end: int
    embargo_end: int    # 测试后禁区终点 [test_end, embargo_end)


@dataclass
class NestedFold:
    """一个嵌套折：外层折（训练/测试评估）+ 在外层训练段内滚动的内层折列表（调参用）。"""# noqa: E501

    outer: ValidationFold
    inner: list[ValidationFold]


def _make_validation_fold(
    *,
    level: str,
    outer_index: int,
    inner_index: int | None,
    train_start: int,
    train_bars: int,
    test_bars: int,
    purge_bars: int,
    embargo_bars: int,
    hard_stop: int | None = None,
) -> ValidationFold:
    train_stop = train_start + train_bars
    test_start = train_stop + purge_bars
    test_stop = test_start + test_bars
    embargo_stop = test_stop + embargo_bars
    if hard_stop is not None:
        embargo_stop = min(embargo_stop, hard_stop)
    return ValidationFold(
        level=level, outer_index=outer_index, inner_index=inner_index,
        train_start=train_start, train_end=train_stop,
        test_start=test_start, test_end=test_stop, embargo_end=embargo_stop,
    )


def make_nested_folds(
    n_days: int,
    config: NestedValidationConfig | None = None,
) -> list[NestedFold]:
    """把 n_days 个交易日切成滚动真嵌套折（外层评估 + 内层调参，带 purge/embargo）。

    对齐参照 generate_nested_folds：按交易日下标滚动（矩阵行即交易日，无日历空洞），
    训练段与测试段之间留 purge_bars 隔离（forward return 窗口不跨边界），
    测试段后留 embargo_bars 禁区；内层折完全在外层训练段内滚动。
    天数不足返回空列表（调用方优雅降级），不抛错。
    """
    config = config or NestedValidationConfig()
    outer_required = config.outer_train_bars + config.purge_bars + config.outer_test_bars
    inner_required = config.inner_train_bars + config.purge_bars + config.inner_test_bars
    if n_days < outer_required or config.outer_train_bars < inner_required:
        logger.warning(
            "天数 %d 不足以切嵌套折（外层至少需 %d 天，外层训练段至少容纳一个内层折 %d 天），返回空",
            n_days, outer_required, inner_required,
        )
        return []

    nested: list[NestedFold] = []
    outer_start = 0
    outer_index = 0
    while outer_start + outer_required <= n_days:
        outer = _make_validation_fold(
            level="outer", outer_index=outer_index, inner_index=None,
            train_start=outer_start, train_bars=config.outer_train_bars,
            test_bars=config.outer_test_bars, purge_bars=config.purge_bars,
            embargo_bars=config.embargo_bars,
        )
        inner_folds: list[ValidationFold] = []
        inner_start = outer_start
        inner_index = 0
        outer_train_stop = outer_start + config.outer_train_bars
        while inner_start + inner_required <= outer_train_stop:
            inner_folds.append(_make_validation_fold(
                level="inner", outer_index=outer_index, inner_index=inner_index,
                train_start=inner_start, train_bars=config.inner_train_bars,
                test_bars=config.inner_test_bars, purge_bars=config.purge_bars,
                embargo_bars=config.embargo_bars, hard_stop=outer_train_stop,
            ))
            inner_index += 1
            inner_start += config.inner_step_bars
        nested.append(NestedFold(outer=outer, inner=inner_folds))
        outer_index += 1
        outer_start += config.outer_step_bars
    return nested


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
    n_obs: int = 0  # 样本外有效日收益条数（DSR 用）
    # 日收益矩（DSR 偏度/峰度校正；可选，缺省按无偏斜/正态峰度假定）
    oos_skewness: float | None = None
    oos_kurtosis: float | None = None


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
