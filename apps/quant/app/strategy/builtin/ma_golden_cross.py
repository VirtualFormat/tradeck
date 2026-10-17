"""MA 金叉 — MA5 上穿 MA20，可选要求站上 MA60 与量能配合。"""
from __future__ import annotations

import numpy as np

from app.matrix import EnrichedMatrix
from app.strategy.base import StrategySignals

META = {
    "id": "ma_golden_cross",
    "name": "MA 金叉",
    "description": "MA5 上穿 MA20 当日入场，可选要求收盘站上 MA60 且量比放大；下穿离场。",
    "tags": ["均线", "金叉", "趋势"],
    "params": [
        {"id": "require_above_ma60", "label": "要求收盘站上 MA60", "type": "bool", "default": True},
        {"id": "vol_ratio_min", "label": "最低量比（0 关闭）", "type": "float", "default": 1.2, "min": 0.0, "max": 5.0, "step": 0.1},
    ],
    "scoring": {"momentum_20d": 0.5, "vol_ratio_5d": 0.3, "rsi14": 0.2},
    "order_by": "score",
    "limit": 100,
    "stop_loss": -0.06,
    "max_hold_days": 15,
}


def _prev(arr: np.ndarray) -> np.ndarray:
    """昨日值矩阵（沿时间轴下移一行，第一行 NaN；NaN 参与比较自然得 False）。"""
    out = np.full(arr.shape, np.nan)
    if arr.shape[0] > 1:
        out[1:] = arr[:-1]
    return out


def compute(enriched: EnrichedMatrix, params: dict) -> StrategySignals:
    ma5 = enriched["ma5"]
    ma20 = enriched["ma20"]
    # 金叉：今日 MA5 > MA20 且昨日 MA5 <= MA20；死叉反之
    golden = (ma5 > ma20) & (_prev(ma5) <= _prev(ma20))
    dead = (ma5 < ma20) & (_prev(ma5) >= _prev(ma20))

    entry = golden.copy()
    if params.get("require_above_ma60", True):
        entry &= enriched.base.close > enriched["ma60"]
    vol_min = params.get("vol_ratio_min", 1.2)
    if vol_min:  # None / 0 表示关闭量比过滤
        entry &= enriched["vol_ratio_5d"] >= float(vol_min)

    # 评分：scoring 字段加权和，仅 entry 日有值，其余 NaN
    score = (
        0.5 * enriched["momentum_20d"]
        + 0.3 * enriched["vol_ratio_5d"]
        + 0.2 * enriched["rsi14"]
    )
    return StrategySignals(
        entry=entry,
        exit=dead,
        score=np.where(entry, score, np.nan),
        # 分钟口径参考线（H1）：金叉买入参考线为 MA20 慢线（收盘上穿它即金叉成立的
        # 价格线）。死叉卖出是「均线交叉」而非「价格穿越」，策略不直接产出 exit_ref
        # ——由 runner 经 build_minute_exit_reference 反推防未来函数触发线接线。
        entry_ref=ma20.astype(np.float64),
    )
