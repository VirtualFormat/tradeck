"""MACD 金叉放量 — DIF 上穿 DEA 且柱体转正确认，可选量能过滤。"""
from __future__ import annotations

import numpy as np

from app.matrix import EnrichedMatrix
from app.strategy.base import StrategySignals

META = {
    "id": "macd_golden",
    "name": "MACD 金叉放量",
    "description": "MACD DIF 上穿 DEA 且柱体（2×(DIF-DEA) 口径）为正确认入场，可选要求量比放大；死叉离场。",
    "tags": ["MACD", "金叉", "放量"],
    "params": [
        {"id": "require_volume", "label": "要求量比大于 1", "type": "bool", "default": True},
    ],
    "scoring": {"macd_hist": 0.5, "momentum_20d": 0.5},
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
    dif = enriched["macd_dif"]
    dea = enriched["macd_dea"]
    # 金叉：今日 DIF > DEA 且昨日 DIF <= DEA，且柱体为正确认（双保险，防抖区假金叉）
    golden = (dif > dea) & (_prev(dif) <= _prev(dea)) & (enriched["macd_hist"] > 0)
    dead = (dif < dea) & (_prev(dif) >= _prev(dea))

    entry = golden.copy()
    if params.get("require_volume", True):
        entry &= enriched["vol_ratio_5d"] > 1.0

    score = 0.5 * enriched["macd_hist"] + 0.5 * enriched["momentum_20d"]
    return StrategySignals(
        entry=entry,
        exit=dead,
        score=np.where(entry, score, np.nan),
    )
