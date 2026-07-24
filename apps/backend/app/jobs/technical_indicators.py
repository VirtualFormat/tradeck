"""技术指标 job（读 daily_prices 本地计算 MA/MACD/RSI/BOLL，回写 technical_indicators）

不调任何外部数据源。每只标的取最近 ~250 个交易日收盘价做指标预热，
只 UPSERT 最近 60 个交易日的结果（历史值不变，近期行覆盖写即可）。
"""
from __future__ import annotations

import logging

import pandas as pd

from app.db import get_pool
from app.jobs.daily_kline import TRACKED_SYMBOLS

logger = logging.getLogger(__name__)

# 读库窗口：MA60 + EMA/RSI 预热足够
LOOKBACK_DAYS = 250
# 只回写最近 N 个交易日
WRITE_DAYS = 60


def _round(value: float | None) -> float | None:
    """NaN/None → None，其余保留 4 位小数"""
    if value is None or pd.isna(value):
        return None
    return round(float(value), 4)


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


async def compute_and_store_symbol(symbol: str) -> int:
    """计算单只股票技术指标并 UPSERT 最近 60 个交易日。返回写入条数。"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT date, close FROM daily_prices
            WHERE symbol = $1 AND close IS NOT NULL
            ORDER BY date DESC
            LIMIT $2
            """,
            symbol,
            LOOKBACK_DAYS,
        )
    if len(rows) < 30:  # 数据太少算不出有效指标
        logger.warning(f"not enough daily prices for {symbol}: {len(rows)}")
        return 0

    # 升序排列后计算
    closes = pd.Series(
        [float(r["close"]) for r in reversed(rows)],
        index=pd.Index([r["date"] for r in reversed(rows)], name="date"),
        dtype="float64",
    )
    df = compute_indicators(closes).tail(WRITE_DAYS)

    records = [
        (
            symbol,
            idx,
            _round(row["ma5"]),
            _round(row["ma10"]),
            _round(row["ma20"]),
            _round(row["ma60"]),
            _round(row["ema12"]),
            _round(row["ema26"]),
            _round(row["dif"]),
            _round(row["dea"]),
            _round(row["macd"]),
            _round(row["rsi6"]),
            _round(row["rsi14"]),
            _round(row["boll_upper"]),
            _round(row["boll_mid"]),
            _round(row["boll_lower"]),
        )
        for idx, row in df.iterrows()
    ]

    async with pool.acquire() as conn:
        await conn.executemany(
            """
            INSERT INTO technical_indicators (
                symbol, date, ma5, ma10, ma20, ma60, ema12, ema26,
                dif, dea, macd, rsi6, rsi14, boll_upper, boll_mid, boll_lower
            )
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16)
            ON CONFLICT (symbol, date) DO UPDATE SET
                ma5 = EXCLUDED.ma5, ma10 = EXCLUDED.ma10,
                ma20 = EXCLUDED.ma20, ma60 = EXCLUDED.ma60,
                ema12 = EXCLUDED.ema12, ema26 = EXCLUDED.ema26,
                dif = EXCLUDED.dif, dea = EXCLUDED.dea, macd = EXCLUDED.macd,
                rsi6 = EXCLUDED.rsi6, rsi14 = EXCLUDED.rsi14,
                boll_upper = EXCLUDED.boll_upper, boll_mid = EXCLUDED.boll_mid,
                boll_lower = EXCLUDED.boll_lower,
                computed_at = NOW()
            """,
            records,
        )
    return len(records)


async def run_technical_indicators_job() -> int:
    """定时任务：计算所有跟踪股票的技术指标"""
    logger.info("=== technical indicators job start ===")
    total = 0
    for symbol in TRACKED_SYMBOLS:
        try:
            total += await compute_and_store_symbol(symbol)
        except Exception as e:
            logger.warning(f"technical indicators failed for {symbol}: {e}")
    logger.info(f"=== technical indicators job done: {total} rows ===")
    return total
