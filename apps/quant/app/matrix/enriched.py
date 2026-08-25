"""enriched 指标层：在市场矩阵上预计算技术指标列。

口径说明：
- 全部指标基于 close / volume / amount（原始价口径），同形状 (dates × symbols) 二维数组。
- 窗口预热期（如前 N-1 行）保持 NaN；输入 NaN（停牌）参与计算时结果 NaN，
  绝不用 0 填充——用掩码约束的递推 / 跨列滑窗实现。
- macd_hist 采国内软件口径 = 2 × (DIF − DEA)。
- momentum 为小数口径（close / close[N 天前] − 1，如 0.05 表示 5%）。
- turnover（换手率）需要流通股本，数据层暂无该字段，本层不算，留待数据层补齐后加。
- 纯 numpy 向量化：滑窗类用 np.lib.stride_tricks.sliding_window_view 跨列一次算全标的，
  递推类（EMA/RSI）逐行递推但整列向量化，均无逐股 Python 循环。
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

from app.matrix.market import MarketMatrix


@dataclass
class EnrichedMatrix:
    """市场矩阵 + 预计算指标列：指标名 → (dates × symbols) float64 数组。"""

    base: MarketMatrix
    indicators: dict[str, np.ndarray]

    def __getitem__(self, name: str) -> np.ndarray:
        return self.indicators[name]


# ---------------------------------------------------------------------------
# 基础滑窗工具
# ---------------------------------------------------------------------------


def _valid_windows(arr: np.ndarray, n: int) -> np.ndarray:
    """每个时间窗内 NaN 计数的掩码工具（窗口无 NaN 才允许出数）。"""
    w = sliding_window_view(np.isnan(arr), n, axis=0)  # (T-n+1, S, n)
    return w.any(axis=2)  # True = 窗口内含 NaN，结果应保持 NaN


def _ma(arr: np.ndarray, n: int) -> np.ndarray:
    """简单均线（窗口内任一 NaN 则该期 NaN，预热期 n-1 行 NaN）。"""
    out = np.full(arr.shape, np.nan)
    if arr.shape[0] < n:
        return out
    w = sliding_window_view(arr, n, axis=0)  # (T-n+1, S, n)
    valid = ~np.isnan(w).any(axis=2)
    res = np.where(valid, w.mean(axis=2), np.nan)
    out[n - 1 :] = res
    return out


def _std(arr: np.ndarray, n: int) -> np.ndarray:
    """窗口标准差（有偏方差，ddof=0，与 pandas rolling.std 的口径差异见注释）。

    采用 ddof=0（总体标准差）：国内行情软件 BOLL 普遍用有偏口径，
    且避免窗口小时 ddof=1 的除零问题。
    """
    out = np.full(arr.shape, np.nan)
    if arr.shape[0] < n:
        return out
    w = sliding_window_view(arr, n, axis=0)
    valid = ~np.isnan(w).any(axis=2)
    res = np.where(valid, w.std(axis=2), np.nan)
    out[n - 1 :] = res
    return out


def _rolling_max(arr: np.ndarray, n: int) -> np.ndarray:
    """窗口最大值（窗口内任一 NaN 则该期 NaN）。"""
    out = np.full(arr.shape, np.nan)
    if arr.shape[0] < n:
        return out
    w = sliding_window_view(arr, n, axis=0)
    valid = ~np.isnan(w).any(axis=2)
    res = np.where(valid, w.max(axis=2), np.nan)
    out[n - 1 :] = res
    return out


def _rolling_min(arr: np.ndarray, n: int) -> np.ndarray:
    """窗口最小值（窗口内任一 NaN 则该期 NaN）。"""
    out = np.full(arr.shape, np.nan)
    if arr.shape[0] < n:
        return out
    w = sliding_window_view(arr, n, axis=0)
    valid = ~np.isnan(w).any(axis=2)
    res = np.where(valid, w.min(axis=2), np.nan)
    out[n - 1 :] = res
    return out


# ---------------------------------------------------------------------------
# 递推类（掩码约束：昨日或今日任一缺失则今日 NaN，不停用 0 续命）
# ---------------------------------------------------------------------------


def _masked_recur(arr: np.ndarray, alpha: float) -> np.ndarray:
    """EMA 递推：out[t] = alpha*x[t] + (1-alpha)*out[t-1]，种子 = 首个有效 x。

    x 或昨日值任一 NaN → 今日 NaN（中断后首个有效 x 重新播种，
    与 pandas ewm 的 NaN 语义一致；停牌期间指标保持缺失）。
    """
    out = np.full(arr.shape, np.nan)
    if arr.shape[0] == 0:
        return out
    for t in range(arr.shape[0]):
        prev = out[t - 1]
        x = arr[t]
        if t == 0:
            out[t] = x
            continue
        # 昨日 NaN + 今日有效 → 重新播种（不是「延续停牌前的值」）
        res = np.where(np.isnan(prev), x, alpha * x + (1 - alpha) * prev)
        out[t] = np.where(np.isnan(x), np.nan, res)
    return out


def _ema(arr: np.ndarray, n: int) -> np.ndarray:
    """指数均线，平滑系数 alpha = 2/(n+1)（与 pandas ewm(span=n) 一致）。"""
    return _masked_recur(arr, 2.0 / (n + 1))


def _rsi(close: np.ndarray, n: int = 14) -> np.ndarray:
    """RSI（Wilder 平滑），取值 [0, 100]。

    delta = close[t] - close[t-1]（停牌跨缺口处 delta 为 NaN）；
    涨跌幅分别做 alpha=1/n 的 Wilder EMA（同样掩码约束），RS = avg_gain / avg_loss，
    RSI = 100 - 100/(1+RS)。avg_loss=0 且 avg_gain>0 时 RSI=100，两者皆 0 时 RSI=50（横盘）。
    """
    delta = np.full(close.shape, np.nan)
    if close.shape[0] > 1:
        prev, cur = close[:-1], close[1:]
        delta[1:] = np.where(np.isnan(prev) | np.isnan(cur), np.nan, cur - prev)
    # 涨跌端均为「delta 为 NaN 则该端 NaN」，保证递推中断语义一致
    gain = np.where(np.isnan(delta), np.nan, np.where(delta > 0, delta, 0.0))
    loss = np.where(np.isnan(delta), np.nan, np.where(delta < 0, -delta, 0.0))
    avg_gain = _masked_recur(gain, 1.0 / n)
    avg_loss = _masked_recur(loss, 1.0 / n)
    valid = ~(np.isnan(avg_gain) | np.isnan(avg_loss))
    rs = np.where(valid & (avg_loss > 0), avg_gain / np.where(avg_loss > 0, avg_loss, 1.0), np.nan)
    rsi = np.where(valid, 100.0 - 100.0 / (1.0 + np.where(valid & (avg_loss > 0), rs, 0.0)), np.nan)
    # avg_loss == 0 的特判：有涨无跌 → 100；无涨无跌（横盘）→ 50
    rsi = np.where(valid & (avg_loss == 0) & (avg_gain > 0), 100.0, rsi)
    rsi = np.where(valid & (avg_loss == 0) & (avg_gain == 0), 50.0, rsi)
    # 预热期：首个有效 delta 后仍需 n-1 期平滑才稳定，前 n 行强制 NaN
    if close.shape[0] > 0:
        rsi[:n] = np.nan
    return rsi


# ---------------------------------------------------------------------------
# 组装
# ---------------------------------------------------------------------------


def enrich(base: MarketMatrix) -> EnrichedMatrix:
    """在市场矩阵上预计算全部指标列（同形状二维数组，NaN 传播）。"""
    close, volume = base.close, base.volume

    ma20 = _ma(close, 20)
    std20 = _std(close, 20)
    ema12 = _ema(close, 12)
    ema26 = _ema(close, 26)
    # 标准 MACD：DIF = EMA12 − EMA26；DEA = DIF 的 9 周期 EMA；HIST = 2×(DIF−DEA)（国内软件口径）
    dif = ema12 - ema26
    dea = _ema(dif, 9)
    hist = 2.0 * (dif - dea)

    # 动量：小数口径 close/close[n 天前] − 1；隔停牌（任一端 NaN）结果为 NaN
    def _mom(n: int) -> np.ndarray:
        out = np.full(close.shape, np.nan)
        if close.shape[0] > n:
            prev, cur = close[:-n], close[n:]
            out[n:] = np.where(np.isnan(prev) | np.isnan(cur), np.nan, cur / prev - 1.0)
        return out

    # 量比：当日 volume / 5 日均量；均量为 0（极端连续无量）时置 NaN 防除零
    vol_ma5 = _ma(volume, 5)
    vol_ratio = np.where(np.isnan(vol_ma5) | (vol_ma5 == 0), np.nan, volume / vol_ma5)

    indicators = {
        "ma5": _ma(close, 5),
        "ma10": _ma(close, 10),
        "ma20": ma20,
        "ma60": _ma(close, 60),
        "ema12": ema12,
        "ema26": ema26,
        "macd_dif": dif,
        "macd_dea": dea,
        "macd_hist": hist,
        "rsi14": _rsi(close, 14),
        "boll_upper": ma20 + 2.0 * std20,
        "boll_lower": ma20 - 2.0 * std20,
        "momentum_5d": _mom(5),
        "momentum_20d": _mom(20),
        "vol_ratio_5d": vol_ratio,
        "high_20d": _rolling_max(close, 20),
        "low_20d": _rolling_min(close, 20),
    }
    return EnrichedMatrix(base=base, indicators=indicators)
