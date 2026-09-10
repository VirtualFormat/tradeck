"""分钟级卖出信号盘中触发 — 参考线反推与穿越确认（阶段 H1）。

照搬参照 tick-stock-panel backtest/minute_trigger.py 语义。
"""
from __future__ import annotations

import numpy as np

__all__ = [
    "MINUTE_EXIT_TRIGGER_SIGNALS",
    "unsupported_minute_exit_signals",
    "build_minute_exit_reference",
    "resolve_minute_exit_trigger",
]

# 可盘中回放的卖出信号白名单（照搬参照；tradeck 当前无等价 id 常量，
# 此处登记为本包权威定义）：
#   signal_ma5_breakdown   MA5 跌破
#   signal_ma10_breakdown  MA10 跌破
#   signal_ma20_breakdown  MA20 跌破
#   signal_ma_dead_5_20    MA5/MA20 死叉
MINUTE_EXIT_TRIGGER_SIGNALS = frozenset({
    "signal_ma5_breakdown",
    "signal_ma10_breakdown",
    "signal_ma20_breakdown",
    "signal_ma_dead_5_20",
})


def unsupported_minute_exit_signals(signals: list[str] | tuple[str, ...]) -> list[str]:
    """返回白名单外的信号 id（排序去重；空列表表示全部支持）。"""
    return sorted(set(signals) - MINUTE_EXIT_TRIGGER_SIGNALS)


def build_minute_exit_reference(
    close: np.ndarray,
    fields: dict[str, np.ndarray],
    exit_signal_code: np.ndarray,
    exit_signal_ids: tuple[str, ...],
) -> np.ndarray:
    """为可回放的卖出信号反推当日已知的价格触发线（无未来函数）。

    以 MA5 跌破为例：信号为 close_t < ma5_t（ma5_t 含当日收盘），ma5_t 等于
    （前4日收盘和 + close_t）/ 5，解不等式得触发线 close_t < (5*ma5 - close)/4，
    右端全部昨日已知。盘中价跌破该线则收盘信号必然成立，可盘中成交。

    Args:
        close: 收盘矩阵（dates × symbols，与 fields 值同形状）。
        fields: 指标字段 {"ma5": ..., "ma10": ..., "ma20": ...}（同形状数组）。
        exit_signal_code: 整型信号编码矩阵（code 为 exit_signal_ids 下标）。
        exit_signal_ids: 信号 id 元组。

    Returns:
        float32 触发线矩阵（只读），非白名单/无效位置为 NaN。
    """
    result = np.full(close.shape, np.nan, dtype=np.float32)

    def _apply(code: int, value: np.ndarray) -> None:
        mask = (exit_signal_code == code) & np.isfinite(value) & (value > 0)
        result[mask] = value[mask].astype(np.float32)

    with np.errstate(divide="ignore", invalid="ignore"):
        for code, signal_id in enumerate(exit_signal_ids):
            if signal_id == "signal_ma5_breakdown" and "ma5" in fields:
                _apply(code, (5.0 * fields["ma5"] - close) / 4.0)
            elif signal_id == "signal_ma10_breakdown" and "ma10" in fields:
                _apply(code, (10.0 * fields["ma10"] - close) / 9.0)
            elif signal_id == "signal_ma20_breakdown" and "ma20" in fields:
                _apply(code, (20.0 * fields["ma20"] - close) / 19.0)
            elif (
                signal_id == "signal_ma_dead_5_20"
                and "ma5" in fields
                and "ma20" in fields
            ):
                sum4 = 5.0 * fields["ma5"] - close
                sum19 = 20.0 * fields["ma20"] - close
                _apply(code, (sum19 - 4.0 * sum4) / 3.0)

    result.setflags(write=False)
    return result


def resolve_minute_exit_trigger(
    minute_arr: np.ndarray | None,
    ref_price: float | None,
) -> float | None:
    """分钟收盘确认向下穿越参考线后，返回下一分钟开盘价（照搬参照语义）。

    确认逻辑：存在某分钟收盘 < ref_price 且前一分钟收盘 >= ref_price
    （首根视为在线上方），取首个确认点的下一分钟开盘价。
    无确认穿越 / 参考线无效 / 分钟数据不足时返回 None（降级日K 口径）。
    """
    if minute_arr is None or len(minute_arr) < 2:
        return None
    if ref_price is None or not np.isfinite(ref_price) or ref_price <= 0:
        return None

    ncols = minute_arr.shape[1] if minute_arr.ndim == 2 else 1
    if ncols < 4:
        return None
    opens = minute_arr[:, 0]
    closes = minute_arr[:, 3]
    below = np.isfinite(closes) & (closes < ref_price)
    previous_above = np.empty(len(closes), dtype=bool)
    previous_above[0] = True
    previous_above[1:] = np.isfinite(closes[:-1]) & (closes[:-1] >= ref_price)
    crossings = np.flatnonzero(below & previous_above)
    if crossings.size == 0:
        return None
    next_idx = int(crossings[0]) + 1
    if next_idx >= len(opens) or not np.isfinite(opens[next_idx]) or opens[next_idx] <= 0:
        return None
    return float(opens[next_idx])
