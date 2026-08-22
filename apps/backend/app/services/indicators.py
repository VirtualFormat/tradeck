"""技术指标纯计算（data-api 侧共享，与 collector job 同源逻辑）。

从 collector 的 technical_indicators job 中提取的纯函数/常量，
供 data-api 对非 tracked 标的按需现算（读 daily_prices，不走外部源、
不写库）。collector 侧 job 仍持有同一份算法用于定时批量回写；
两处算法保持一致，不得单侧修改。
"""
from __future__ import annotations

import pandas as pd

# 读库窗口：MA60 + EMA/RSI 预热足够
LOOKBACK_DAYS = 250


def compute_indicators(closes: pd.Series) -> pd.DataFrame:
    """输入按日期升序的收盘价序列，输出各指标列（索引与输入一致）"""
    df = pd.DataFrame(index=closes.index)

    # MA 简单移动平均
    for n in (5, 10, 20, 60):
        df[f"ma{n}"] = closes.rolling(n).mean()

    # EMA（adjust=False 为递归式，与主流行情软件一致）
    df["ema12"] = closes.ewm(span=12, adjust=False).mean()
    df["ema26"] = closes.ewm(span=26, adjust=False).mean()

    # MACD（国内惯例：柱 = 2 × (DIF - DEA)）
    df["dif"] = df["ema12"] - df["ema26"]
    df["dea"] = df["dif"].ewm(span=9, adjust=False).mean()
    df["macd"] = 2 * (df["dif"] - df["dea"])

    # RSI（Wilder 平滑：ewm alpha=1/n 近似 Wilder 递推）
    delta = closes.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    for n in (6, 14):
        avg_gain = gain.ewm(alpha=1 / n, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1 / n, adjust=False).mean()
        rs = avg_gain / avg_loss
        df[f"rsi{n}"] = 100 - 100 / (1 + rs)

    # BOLL(20, 2)：中轨 = MA20，上下轨 = 中轨 ± 2 × 20 日标准差
    df["boll_mid"] = df["ma20"]
    std20 = closes.rolling(20).std()
    df["boll_upper"] = df["boll_mid"] + 2 * std20
    df["boll_lower"] = df["boll_mid"] - 2 * std20

    return df
