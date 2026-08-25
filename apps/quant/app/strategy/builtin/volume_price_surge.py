"""量价齐升 — 5 日动量与量比同时放大入场，量缩回常态离场。"""
from __future__ import annotations

import numpy as np

from app.matrix import EnrichedMatrix
from app.strategy.base import StrategySignals

META = {
    "id": "volume_price_surge",
    "name": "量价齐升",
    "description": "5 日动量超过阈值且量比显著放大入场，量比回落到 1 以下离场。",
    "tags": ["量价", "动量", "放量"],
    "params": [
        {"id": "mom_min", "label": "最低 5 日动量", "type": "float", "default": 0.05, "min": 0.0, "max": 0.3, "step": 0.01},
        {"id": "vol_min", "label": "最低量比", "type": "float", "default": 2.0, "min": 1.0, "max": 10.0, "step": 0.1},
    ],
    "scoring": {"momentum_5d": 0.5, "vol_ratio_5d": 0.5},
    "order_by": "score",
    "limit": 100,
    "stop_loss": -0.05,
    "max_hold_days": 10,
}


def compute(enriched: EnrichedMatrix, params: dict) -> StrategySignals:
    mom = enriched["momentum_5d"]
    vol = enriched["vol_ratio_5d"]
    entry = (mom > float(params.get("mom_min", 0.05))) & (vol > float(params.get("vol_min", 2.0)))
    exit_ = vol < 1.0

    score = 0.5 * mom + 0.5 * vol
    return StrategySignals(
        entry=entry,
        exit=exit_,
        score=np.where(entry, score, np.nan),
    )
