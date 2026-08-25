"""因子目录 — 从 enriched 矩阵派生可挖掘的日频因子。

每个因子一个 (dates × symbols) 数组（与矩阵同形状，NaN 传播）。
V1 边界（对齐参照 mining.md）：只用本地日频数据派生的价量/形态/流动性因子，
不生成任意公式、不用分钟数据、不接扩展数据源。财务因子走 data-api as-of（另议）。

时点红线：因子在 T 日的值只能用 T 日及之前的数据（动量/波动/极值天然满足；
收益形态类用 rolling 窗口，窗口右端含当日）。
"""
from __future__ import annotations

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

from app.matrix import EnrichedMatrix


def _shift(arr: np.ndarray, n: int) -> np.ndarray:
    """沿时间轴下移 n 行（前 n 行 NaN）。"""
    out = np.full(arr.shape, np.nan)
    if arr.shape[0] > n:
        out[n:] = arr[:-n]
    return out


def _rolling(arr: np.ndarray, n: int, fn) -> np.ndarray:
    """窗口聚合（窗口内任一 NaN 则该期 NaN，预热期 NaN）。"""
    out = np.full(arr.shape, np.nan)
    if arr.shape[0] < n:
        return out
    w = sliding_window_view(arr, n, axis=0)
    valid = ~np.isnan(w).any(axis=2)
    res = np.where(valid, fn(w, axis=2), np.nan)
    out[n - 1 :] = res
    return out


def _daily_ret(close: np.ndarray) -> np.ndarray:
    """日收益率（小数），首行与跨停牌为 NaN。"""
    prev = _shift(close, 1)
    return np.where(np.isnan(prev) | np.isnan(close), np.nan, close / prev - 1.0)


def factor_catalog(enriched: EnrichedMatrix) -> dict[str, np.ndarray]:
    """派生全部可挖掘因子，返回 {因子名: (dates × symbols)}。

    分四类（命名即口径，注释标注金融含义与预期方向）：
    """
    base = enriched.base
    close, volume, amount = base.close, base.volume, base.amount
    ind = enriched.indicators
    ret = _daily_ret(close)

    factors: dict[str, np.ndarray] = {}

    # ── 动量/趋势（已有指标直接复用 + 派生）──────────────────
    factors["momentum_5d"] = ind["momentum_5d"]      # 5 日动量（小数）
    factors["momentum_20d"] = ind["momentum_20d"]    # 20 日动量
    # 均线偏离：收盘价相对均线的偏离度（趋势强度，正向）
    for p in (5, 10, 20, 60):
        ma = ind[f"ma{p}"]
        factors[f"ma{p}_bias"] = np.where(
            np.isnan(ma) | (ma == 0), np.nan, close / ma - 1.0
        )

    # ── 波动率（反向：低波动异象）───────────────────────────
    factors["volatility_20d"] = _rolling(ret, 20, lambda w, axis: w.std(axis=axis))

    # ── 收益形态（A 股实证维度）─────────────────────────────
    # 彩票效应：20 日最大单日涨幅（正向偏好彩票型，实证上未来收益反而低 → 反向候选）
    factors["max_ret_20d"] = _rolling(ret, 20, lambda w, axis: w.max(axis=axis))
    # 收益偏度：20 日收益分布偏度（右偏=彩票型）
    factors["ret_skew_20d"] = _rolling(ret, 20, lambda w, axis: _skew(w, axis))
    # 上涨天数占比：20 日内收阳比例（趋势持续性）
    up = np.where(np.isnan(ret), np.nan, (ret > 0).astype(float))
    factors["up_days_20d"] = _rolling(up, 20, lambda w, axis: w.mean(axis=axis))

    # ── 流动性（反向：低流动性溢价 / 换手异动）──────────────
    # Amihud 非流动性：|收益| / 成交额（值越大流动性越差，实证正向溢价）
    illiq = np.where(
        np.isnan(ret) | np.isnan(amount) | (amount == 0), np.nan,
        np.abs(ret) / (amount / 1e8),  # 成交额归一到亿，避免数值过小
    )
    factors["amihud_20d"] = _rolling(illiq, 20, lambda w, axis: w.mean(axis=axis))
    # 量比（短期换手异动）
    factors["vol_ratio_5d"] = ind["vol_ratio_5d"]

    # ── 超买超卖（反转）────────────────────────────────────
    factors["rsi14"] = ind["rsi14"]                  # 高=超买（反向）
    # 距 20 日高点距离（突破/乖离）
    h20 = ind["high_20d"]
    factors["dist_to_high_20d"] = np.where(
        np.isnan(h20) | (h20 == 0), np.nan, close / h20 - 1.0
    )

    return factors


def _skew(w: np.ndarray, axis: int) -> np.ndarray:
    """窗口偏度（Fisher，ddof=0），常数窗口返回 0。"""
    mean = w.mean(axis=axis, keepdims=True)
    dev = w - mean
    m3 = (dev ** 3).mean(axis=axis)
    m2 = (dev ** 2).mean(axis=axis)
    std = np.sqrt(m2)
    return np.where(std > 0, m3 / (std ** 3 + 1e-12), 0.0)


# 因子元信息：{因子名: (中文说明, 预期方向)}，direction: 1=正向（值大未来涨）, -1=反向
# 预期方向仅作展示与方向自动判定的参考，实际方向由训练折 RankIC 符号决定（见 mining/core）。
FACTOR_META: dict[str, tuple[str, int]] = {
    "momentum_5d": ("5 日动量", 1),
    "momentum_20d": ("20 日动量", 1),
    "ma5_bias": ("MA5 偏离", 1),
    "ma10_bias": ("MA10 偏离", 1),
    "ma20_bias": ("MA20 偏离", 1),
    "ma60_bias": ("MA60 偏离", 1),
    "volatility_20d": ("20 日波动率", -1),
    "max_ret_20d": ("20 日最大单日涨幅（彩票）", -1),
    "ret_skew_20d": ("20 日收益偏度", -1),
    "up_days_20d": ("20 日上涨天数占比", 1),
    "amihud_20d": ("Amihud 非流动性", 1),
    "vol_ratio_5d": ("量比（5 日）", 1),
    "rsi14": ("RSI14（超买超卖）", -1),
    "dist_to_high_20d": ("距 20 日高点距离", 1),
}
