"""选股执行器 — 与回测共用「矩阵 → 复权 → enrich → 策略信号」管线，取最新交易日截面。

流程（对齐 docs/QUANT-BACKTEST.md 的 screener 设计）：
  加载策略 → basic_filter 先行收窄（两阶段过滤）→ registry.run 全窗口信号
  → 最新交易日截面 entry=True 入选 → 按 score 排序（NaN 排最后）→ 截 limit。

降级约定（与引擎全局一致）：
- 无缓存数据标的在矩阵层为全 NaN 列，自然不出信号，不报错；
- 无任何缓存数据时返回空 rows（不抛错）；
- 缺除权因子的标的降级无复权，列入 result.unadjusted。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np

from app.data import factors, store
from app.engine import forward_adjust
from app.matrix import build, enrich
from app.runner import _default_strategy_dirs
from app.strategy import StrategyRegistry

logger = logging.getLogger(__name__)

# 截面窗口：取最近 ~90 个自然日（约 60 个交易日）。
# 依据：选股只看最新截面，但指标需预热 —— enriched 最长窗口为 ma60，
# RSI14 另有 14 行预热 + 递推稳定期；60 个交易日足以让全部指标出数，
# 又不至于把全历史读进内存（全市场扫描时内存敏感）。
_SCREEN_WINDOW_DAYS = 90

# META.basic_filter 支持的键（价格/成交额过滤，口径为最新交易日截面值）
_BASIC_FILTER_KEYS = ("price_min", "price_max", "amount_min", "exclude_st")


@dataclass
class ScreenRow:
    """单个入选标的的最新交易日截面。"""

    symbol: str
    # 暂无名称表，先填 symbol；待数据层补名称映射后在此替换
    name: str
    score: float
    signals: dict  # {"entry": bool, "exit": bool} 最新交易日状态
    market: str  # CN/HK/US（与 data/store._market_of 同款后缀规则）


@dataclass
class ScreenResult:
    """一次选股执行的输出。"""

    strategy_id: str
    as_of: date  # 截面交易日（缓存窗口内最新交易日）
    rows: list[ScreenRow]  # 按 score 排序（NaN 排最后），已截 limit
    total: int  # 入选总数（截 limit 前）
    unadjusted: list[str] = field(default_factory=list)  # 无因子降级标的


def _apply_basic_filter(
    meta_filter: dict, close: np.ndarray, amount: np.ndarray
) -> np.ndarray:
    """basic_filter 第一阶段过滤：返回各标的的通过掩码（True=允许参与评分）。

    只认白名单键（price_min/price_max/amount_min/exclude_st），未知键忽略并告警。
    exclude_st 需要名称表判定，数据层暂无该表，当前跳过（待名称表接入后实现）。
    价格为 NaN（停牌/无数据）的标的一律不通过。
    """
    mask = np.ones(close.shape, dtype=bool)
    unknown = set(meta_filter) - set(_BASIC_FILTER_KEYS)
    if unknown:
        logger.warning("basic_filter 含不支持键 %s，已忽略", sorted(unknown))
    if "price_min" in meta_filter:
        mask &= close >= float(meta_filter["price_min"])
    if "price_max" in meta_filter:
        mask &= close <= float(meta_filter["price_max"])
    if "amount_min" in meta_filter:
        # 成交额 NaN 视为不满足（无成交记录的标的不入选）
        mask &= np.where(np.isnan(amount), False, amount >= float(meta_filter["amount_min"]))
    if meta_filter.get("exclude_st"):
        # 待名称表接入，当前跳过（ST 判定需要证券名称，数据层尚无名称表）
        logger.info("basic_filter.exclude_st 暂跳过：名称表未接入")
    # 价格缺失的标的不通过（全 NaN 列/当日停牌）
    mask &= ~np.isnan(close)
    return mask


def screen(
    strategy_id: str,
    symbols: list[str],
    end_date: date | None = None,
    params: dict | None = None,
    registry: StrategyRegistry | None = None,
) -> ScreenResult:
    """在给定标的池上执行策略选股，返回最新交易日截面结果。

    与 runner.run_backtest 共用同一条数据管线，保证选股/回测信号口径一致。
    """
    reg = registry or StrategyRegistry(_default_strategy_dirs())
    strat = reg.get(strategy_id)  # 先取定义，策略不存在时尽早报错（不白跑矩阵）

    end = end_date or date.today()
    start = end - timedelta(days=_SCREEN_WINDOW_DAYS)

    matrix = build(symbols, start, end)
    if not matrix.dates:
        logger.warning("标的池在 %s ~ %s 无缓存数据，返回空结果", start, end)
        return ScreenResult(strategy_id=strategy_id, as_of=end, rows=[], total=0,
                            unadjusted=list(symbols))

    # 复权：与回测同款（缺因子标的降级无复权并标注）
    fac = {s: factors.load(s) for s in matrix.symbols}
    adjusted_matrix, adjusted_flags = forward_adjust(matrix, fac)
    unadjusted = [s for s, ok in adjusted_flags.items() if not ok]

    # 两阶段过滤：basic_filter 先行收窄，再跑策略评分
    last = len(matrix.dates) - 1
    meta_filter = strat.meta.get("basic_filter") or {}
    if isinstance(meta_filter, dict) and meta_filter:
        eligible = _apply_basic_filter(
            meta_filter, adjusted_matrix.close[last], adjusted_matrix.amount[last]
        )
    else:
        eligible = np.ones(len(matrix.symbols), dtype=bool)

    enriched = enrich(adjusted_matrix)
    signals = reg.run(strategy_id, enriched, params)

    # 最新交易日截面：entry=True 且通过 basic_filter 的标的入选
    entry_row = signals.entry[last] & eligible
    exit_row = signals.exit[last]
    score_row = signals.score[last]
    as_of = matrix.dates[last]

    # 排序：score 降序（META.descending 默认 True），NaN 排最后（不丢弃）
    descending = bool(strat.meta.get("descending", True))
    picked = [j for j in range(len(matrix.symbols)) if entry_row[j]]

    def _sort_key(j: int) -> tuple[bool, float]:
        s = score_row[j]
        nan = bool(np.isnan(s))
        val = float(s) if not nan else 0.0
        # 降序取负值，使两种方向下 NaN 都稳定落在队尾
        return (nan, -val if descending else val)

    picked.sort(key=_sort_key)

    limit = int(strat.meta.get("limit", 100))
    total = len(picked)
    rows = [
        ScreenRow(
            symbol=matrix.symbols[j],
            name=matrix.symbols[j],  # 待名称表
            score=float(score_row[j]) if not np.isnan(score_row[j]) else float("nan"),
            signals={"entry": bool(entry_row[j]), "exit": bool(exit_row[j])},
            market=store._market_of(matrix.symbols[j]),
        )
        for j in picked[:limit]
    ]
    logger.info(
        "screen %s: 截面 %s，入选 %d 只（截 limit %d），未复权 %d 只",
        strategy_id, as_of, total, limit, len(unadjusted),
    )
    return ScreenResult(
        strategy_id=strategy_id, as_of=as_of, rows=rows, total=total, unadjusted=unadjusted
    )
