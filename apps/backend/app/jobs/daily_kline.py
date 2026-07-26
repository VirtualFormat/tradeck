"""盘后拉日 K 线（调 TickFlow，写入 daily_prices）"""
from __future__ import annotations

import logging

from app.datasource import tickflow_source
from app.db import get_pool
from app.markets import pick_market

logger = logging.getLogger(__name__)


# 跟踪的股票（100 只）
TRACKED_SYMBOLS = [
    # ── 美股科技（30）──
    "AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "GOOGL", "META", "NFLX",
    "AMD", "INTC", "AVGO", "QCOM", "ADBE", "CRM", "ORCL", "CSCO",
    "ACN", "IBM", "NOW", "UBER", "LYFT", "SNAP", "PINS", "SHOP",
    "SQ", "PYPL", "COIN", "PLTR", "SNOW", "ZM",
    # ── 美股金融/消费/医疗（20）──
    "JPM", "BAC", "WFC", "GS", "MS", "C", "BLK", "V", "MA", "AXP",
    "WMT", "COST", "HD", "MCD", "NKE", "SBUX", "DIS", "KO", "PEP", "PG",
    # ── 美股能源/工业（10）──
    "XOM", "CVX", "COP", "SLB", "EOG", "BA", "CAT", "GE", "HON", "UPS",
    # ── A 股（30）──（沪市用 .SH，与 TickFlow/业界一致）
    "600519.SH", "601318.SH", "600036.SH", "000858.SZ", "002594.SZ",
    "300750.SZ", "601012.SH", "600900.SH", "000001.SZ", "601166.SH",
    "600276.SH", "601398.SH", "000333.SZ", "600030.SH", "601888.SH",
    "600031.SH", "000651.SZ", "002415.SZ", "300059.SZ", "600009.SH",
    "601628.SH", "600585.SH", "000568.SZ", "002714.SZ", "600436.SH",
    "603259.SH", "601857.SH", "600028.SH", "601088.SH", "600019.SH",
    # ── 港股（10）──（5 位补零，与 TickFlow/业界一致）
    "00700.HK", "09988.HK", "01810.HK", "03690.HK", "09618.HK",
    "00005.HK", "01299.HK", "00883.HK", "00939.HK", "02318.HK",
]


async def fetch_and_store_daily_kline(symbol: str) -> int:
    """拉单只股票日 K 线（TickFlow），写入 DB。返回写入条数。"""
    market = pick_market(symbol)

    # 拉近 1 年（~250 交易日，取 365 覆盖）
    results = await tickflow_source.get_daily_kline(symbol, count=365)
    if not results:
        logger.warning(f"No daily kline for {symbol}")
        return 0

    pool = await get_pool()
    async with pool.acquire() as conn:
        # 批量 UPSERT（tickflow_source 已返回 date 对象）
        rows = [
            (symbol, market, r["date"], r["open"], r["high"],
             r["low"], r["close"], r["volume"])
            for r in results
            if r.get("close") is not None  # 跳过 null close 行，防止覆盖有效值
        ]
        await conn.executemany(
            """
            INSERT INTO daily_prices (symbol, market, date, open, high, low, close, volume)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (symbol, date) DO UPDATE SET
                open = EXCLUDED.open, high = EXCLUDED.high,
                low = EXCLUDED.low, close = EXCLUDED.close,
                volume = EXCLUDED.volume
            """,
            rows,
        )
    logger.info(f"fetched {len(rows)} daily prices for {symbol}")
    return len(rows)


async def run_daily_kline_job() -> None:
    """定时任务：拉所有跟踪股票的日 K 线"""
    logger.info("=== daily kline job start ===")
    total = 0
    for symbol in TRACKED_SYMBOLS:
        count = await fetch_and_store_daily_kline(symbol)
        total += count
    logger.info(f"=== daily kline job done: {total} rows ===")
