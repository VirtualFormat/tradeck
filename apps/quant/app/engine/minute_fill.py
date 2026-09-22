"""分钟精确成交价 — 信号触发日用当日分钟K 优化成交价（阶段 H1）。

照搬参照 tick-stock-panel engine._resolve_minute_fill 语义：
- 有参考线（ref_price，如 MA5 值）→ 穿越价成交：
  buy 找价格涨破参考线（开盘已高于则按 open，否则高点触及按 ref_price，
  当日始终未穿越则按收盘——视为信号确认价）；sell 对称（跌破）。
- 无参考线 → VWAP（sum(amount)/sum(volume)），量额缺失/为零时退化当日收盘。
- 分钟数据缺失/为空 → 返回 None，调用方降级日K 口径（优雅降级，不抛错）。
"""
from __future__ import annotations

import numpy as np

__all__ = ["resolve_minute_fill", "resolve_minute_fill_with_mode"]


def _valid_price(value: float) -> bool:
    return bool(np.isfinite(value) and value > 0)


def resolve_minute_fill_with_mode(
    minute_arr: np.ndarray | None,
    ref_price: float | None,
    side: str,
) -> tuple[float | None, str | None]:
    """用当日分钟K 确定精确成交价，并带出成交模式标注（缺陷 4：模式唯一出处）。

    Args:
        minute_arr: 当日分钟K，float64 2D 数组，列序 [open, high, low, close,
                    volume, amount]（尾部列可缺失，按 shape 判定）。
        ref_price: 信号参考线价格（如 MA5 值）；None 表示无参考线。
        side: "buy" 或 "sell"，决定穿越方向。

    返回 (价格, 模式)：模式 ∈ minute_ref（穿越价）/ minute_vwap（无参考线）/
    minute_close（有参考线当日未穿越的信号确认收盘价）；分钟数据缺失/为空
    返回 (None, None)（降级日K 口径）。matcher 等调用方应直接消费本函数的
    模式返回值，不要在调用侧重复推导穿越判定（避免两处实现未来分叉）。
    """
    if minute_arr is None or len(minute_arr) == 0:
        return None, None

    ncols = minute_arr.shape[1] if minute_arr.ndim == 2 else 1
    opens = minute_arr[:, 0]
    highs = minute_arr[:, 1] if ncols > 1 else opens
    lows = minute_arr[:, 2] if ncols > 2 else opens
    closes = minute_arr[:, 3] if ncols > 3 else opens
    volumes = minute_arr[:, 4] if ncols > 4 else None
    amounts = minute_arr[:, 5] if ncols > 5 else None

    # 有参考线 → 穿越价成交（逻辑同止损：找价格穿越参考线的时刻）
    if ref_price is not None and _valid_price(ref_price):
        if side == "sell":
            # 卖出：价格跌破参考线 → 开盘已低于则按开盘；否则按参考线（低点触及）
            if np.isfinite(opens[0]) and opens[0] <= ref_price:
                return float(opens[0]), "minute_ref"
            if np.any(np.isfinite(lows) & (lows <= ref_price)):
                return float(ref_price), "minute_ref"
        else:
            # 买入：价格涨破参考线 → 开盘已高于则按开盘；否则按参考线（高点触及）
            if np.isfinite(opens[0]) and opens[0] >= ref_price:
                return float(opens[0]), "minute_ref"
            if np.any(np.isfinite(highs) & (highs >= ref_price)):
                return float(ref_price), "minute_ref"
        # 参考线存在但当日分钟K 未穿越 → 用收盘（信号确认）
        if np.isfinite(closes[-1]):
            return float(closes[-1]), "minute_close"
        return None, None

    # 无参考线 → VWAP（成交额/成交量），退化到收盘价
    if volumes is not None and amounts is not None:
        total_vol = float(np.nansum(volumes))
        total_amt = float(np.nansum(amounts))
        if total_vol > 0 and total_amt > 0:
            return total_amt / total_vol, "minute_vwap"

    if np.isfinite(closes[-1]):
        return float(closes[-1]), "minute_vwap"
    return None, None


def resolve_minute_fill(
    minute_arr: np.ndarray | None,
    ref_price: float | None,
    side: str,
) -> float | None:
    """resolve_minute_fill_with_mode 的兼容包装：只取价格，丢弃模式标注。

    保留旧签名供既有调用方（如 engine.minute_replay）使用；新代码应直接
    调用 resolve_minute_fill_with_mode 消费模式，不要自行推导穿越判定。
    """
    price, _mode = resolve_minute_fill_with_mode(minute_arr, ref_price, side)
    return price
