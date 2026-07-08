"""盘后拉日 K 线（调 OpenBB historical，写入 daily_prices）"""
from __future__ import annotations

import logging
from datetime import date, timedelta

from app.db import get_pool
from app.markets import pick_market, pick_provider
from app.openbb_client import fetch_openbb

logger = logging.getLogger(__name__)

# 默认跟踪的股票（阶段 1：热门股，后续可扩展）
TRACKED_SYMBOLS = [
    # 美股
    "AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "GOOGL", "META", "NFLX",
    # A 股
    "600519.SH", "000001.SZ", "300750.SZ", "601318.SH",
    # 港股
    "0700.HK", "9988.HK", "1810.HK",
]


async def fetch_and_store_daily_kline(symbol: str) -> int:
    """拉单只股票日 K 线，写入 DB。返回写入条数。"""
    provider = pick_provider(symbol)
    market = pick_market(symbol)

    # 拉 1 年历史
    end = date.today().isoformat()
    start = (date.today() - timedelta(days=365)).isoformat()

    data = await fetch_openbb(
        "/equity/price/historical",
        {
            "provider": provider,
            "symbol": symbol,
            "start_date": start,
            "end_date": end,
        },
    )
    results = data.get("results", [])
    if not results:
        logger.warning(f"No daily kline for {symbol} ({provider})")
        return 0

    pool = await get_pool()
    async with pool.acquire() as conn:
        # 批量 UPSERT
        rows = [
            (symbol, market, r.get("date"), r.get("open"), r.get("high"),
             r.get("low"), r.get("close"), r.get("volume"))
            for r in results
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
    logger.info(f"fetched {len(results)} daily prices for {symbol}")
    return len(results)


async def run_daily_kline_job() -> None:
    """定时任务：拉所有跟踪股票的日 K 线"""
    logger.info("=== daily kline job start ===")
    total = 0
    for symbol in TRACKED_SYMBOLS:
        count = await fetch_and_store_daily_kline(symbol)
        total += count
    logger.info(f"=== daily kline job done: {total} rows ===")
