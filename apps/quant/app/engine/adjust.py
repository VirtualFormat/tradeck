"""动态复权 — 原始价 × 除权因子合成前复权序列（引擎内做，日K 保持原始价入库）。

口径（与 tick-stock-panel 一致的前复权原理）：
- 数据为原始价。除权因子表为 {date, ex_factor}（除权日生效的累计因子）。
- 前复权价[t] = 原始价[t] × factor[t] / factor[T_last]（T_last = 最新交易日），
  即历史价向最新价看齐，最新价 = 原始价（便于对照真实市价）。
- OHLC 同乘一个比例（保持 K 线形态），volume 反除（成交金额不变），amount 不变。
- 无因子的标的：原样返回 + adjusted=False（优雅降级，报告需标注未复权）。
"""
from __future__ import annotations

import numpy as np
import polars as pl

from app.matrix import MarketMatrix

# 需要按比例缩放的字段（volume 反向，amount 不动）
_PRICE_FIELDS = ("open", "high", "low", "close")


def _factor_series(factors: pl.DataFrame, dates: list) -> np.ndarray:
    """把 {date, ex_factor} 因子表对齐到交易日轴：每日取当日及之前最近因子。

    因子表为空 → 全 1.0（无复权）。首个因子日之前的交易日取首个因子（向历史延伸）。
    """
    if factors.is_empty():
        return np.ones(len(dates))
    f_dates = factors["date"].to_list()
    f_vals = factors["ex_factor"].to_numpy()
    out = np.empty(len(dates))
    for i, d in enumerate(dates):
        idx = np.searchsorted(f_dates, d, side="right") - 1
        out[i] = f_vals[max(idx, 0)]
    return out


def forward_adjust(
    matrix: MarketMatrix, factors_by_symbol: dict[str, pl.DataFrame]
) -> tuple[MarketMatrix, dict[str, bool]]:
    """对市场矩阵做前复权；返回 (复权矩阵, {symbol: 是否真有因子}）。"""
    adjusted: dict[str, bool] = {}
    scale = np.ones((len(matrix.dates), len(matrix.symbols)))
    for j, sym in enumerate(matrix.symbols):
        fac = factors_by_symbol.get(sym)
        if fac is None or fac.is_empty():
            adjusted[sym] = False
            continue
        series = _factor_series(fac, matrix.dates)
        last = series[-1] if series[-1] != 0 else 1.0
        scale[:, j] = series / last
        adjusted[sym] = True

    new_fields = {f: getattr(matrix, f) * scale for f in _PRICE_FIELDS}
    safe_scale = np.where(scale == 0, 1.0, scale)  # 极端保底防 inf
    new_fields["volume"] = matrix.volume / safe_scale
    return (
        MarketMatrix(
            dates=matrix.dates,
            symbols=matrix.symbols,
            open=new_fields["open"],
            high=new_fields["high"],
            low=new_fields["low"],
            close=new_fields["close"],
            volume=new_fields["volume"],
            amount=matrix.amount,
        ),
        adjusted,
    )
