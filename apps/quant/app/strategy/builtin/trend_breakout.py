"""趋势突破 — 收盘创 20 日新高且 20 日动量为正入场，跌破 MA20 离场。"""
from __future__ import annotations

import numpy as np

from app.matrix import EnrichedMatrix
from app.strategy.base import StrategySignals

META = {
    "id": "trend_breakout",
    "name": "趋势突破",
    "description": "收盘价创 20 日新高且 20 日动量为正入场，回落跌破 MA20 离场。",
    "tags": ["突破", "趋势", "动量"],
    "scoring": {"momentum_20d": 0.7, "vol_ratio_5d": 0.3},
    "order_by": "score",
    "limit": 100,
}


def _prev(arr: np.ndarray) -> np.ndarray:
    """昨日值矩阵（沿时间轴下移一行，第一行 NaN）。"""
    out = np.full(arr.shape, np.nan)
    if arr.shape[0] > 1:
        out[1:] = arr[:-1]
    return out


def compute(enriched: EnrichedMatrix, params: dict) -> StrategySignals:
    del params  # 本策略无可调参数
    close = enriched.base.close
    high_20d = enriched["high_20d"]
    ma20 = enriched["ma20"]
    # 创 20 日新高：今日收盘等于 20 日窗口最高收盘，且昨日收盘未触及昨日高点（首破口径）
    entry = (close == high_20d) & (_prev(close) < _prev(high_20d)) & (enriched["momentum_20d"] > 0)
    exit_ = (_prev(close) >= _prev(ma20)) & (close < ma20)

    score = 0.7 * enriched["momentum_20d"] + 0.3 * enriched["vol_ratio_5d"]
    return StrategySignals(
        entry=entry,
        exit=exit_,
        score=np.where(entry, score, np.nan),
    )
