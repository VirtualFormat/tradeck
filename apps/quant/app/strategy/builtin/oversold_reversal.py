"""超卖反转 — RSI14 跌破阈值后收阳入场，RSI 过热离场（低 RSI 优先）。"""
from __future__ import annotations

import numpy as np

from app.matrix import EnrichedMatrix
from app.strategy.base import StrategySignals

META = {
    "id": "oversold_reversal",
    "name": "超卖反转",
    "description": "RSI14 低于超卖阈值且当日收阳（close > open）入场，RSI 升破 70 离场；评分低 RSI 优先。",
    "tags": ["超卖", "反转", "RSI"],
    "params": [
        {"id": "rsi_threshold", "label": "RSI 超卖阈值", "type": "float", "default": 30.0, "min": 10.0, "max": 50.0, "step": 1.0},
    ],
    "scoring": {"rsi14": 0.5, "momentum_5d": 0.5},
    "order_by": "score",
    "limit": 100,
}


def compute(enriched: EnrichedMatrix, params: dict) -> StrategySignals:
    rsi = enriched["rsi14"]
    threshold = float(params.get("rsi_threshold", 30.0))
    # 入场：RSI 超卖 + 当日收阳（多头开始反攻的初步确认）
    entry = (rsi < threshold) & (enriched.base.close > enriched.base.open)
    exit_ = rsi > 70.0

    # 评分：RSI 越低越好，故取负值（-rsi 越大代表越超卖），权重方向与 META.scoring 一致
    score = 0.5 * (-rsi) + 0.5 * enriched["momentum_5d"]
    return StrategySignals(
        entry=entry,
        exit=exit_,
        score=np.where(entry, score, np.nan),
    )
