"""布林突破 — 收盘价向上突破布林上轨入场，回落跌破 MA20 离场。"""
from __future__ import annotations

import numpy as np

from app.matrix import EnrichedMatrix
from app.strategy.base import StrategySignals

META = {
    "id": "boll_breakout",
    "name": "布林突破",
    "description": "收盘价上穿布林上轨（MA20 + 2 倍标准差）入场，回落跌破 MA20 离场。",
    "tags": ["布林", "突破"],
    "scoring": {"momentum_20d": 0.6, "vol_ratio_5d": 0.4},
    "order_by": "score",
    "limit": 100,
    "stop_loss": -0.07,
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
    upper = enriched["boll_upper"]
    ma20 = enriched["ma20"]
    # 上穿上轨：昨日 close <= 昨日上轨，今日 close > 今日上轨
    entry = (_prev(close) <= _prev(upper)) & (close > upper)
    # 离场：收盘跌破 MA20（下穿口径，避免持续位于线下时反复触发）
    exit_ = (_prev(close) >= _prev(ma20)) & (close < ma20)

    score = 0.6 * enriched["momentum_20d"] + 0.4 * enriched["vol_ratio_5d"]
    return StrategySignals(
        entry=entry,
        exit=exit_,
        score=np.where(entry, score, np.nan),
        # 分钟口径参考线（H1）：买入参考线为布林上轨、卖出参考线为 MA20
        # （均为当日信号的价格穿越线，供 minute_fill 穿越价成交用）。
        entry_ref=upper.astype(np.float64),
        exit_ref=ma20.astype(np.float64),
    )
