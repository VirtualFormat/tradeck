"""盘后拉日 K 线（调 OpenBB historical，写入 daily_prices）"""
from __future__ import annotations

import logging
from datetime import date, timedelta

from app.db import get_pool
from app.markets import pick_market, pick_provider
from app.openbb_client import fetch_openbb

logger = logging.getLogger(__name__)


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except Exception:
        return None


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
    # ── A 股（30）──
    "600519.SS", "601318.SS", "600036.SS", "000858.SZ", "002594.SZ",
    "300750.SZ", "601012.SS", "600900.SS", "000001.SZ", "601166.SS",
    "600276.SS", "601398.SS", "000333.SZ", "600030.SS", "601888.SS",
    "600031.SS", "000651.SZ", "002415.SZ", "300059.SZ", "600009.SS",
    "601628.SS", "600585.SS", "000568.SZ", "002714.SZ", "600436.SS",
    "603259.SS", "601857.SS", "600028.SS", "601088.SS", "600019.SS",
    # ── 港股（10）──
    "0700.HK", "9988.HK", "1810.HK", "3690.HK", "9618.HK",
    "0005.HK", "1299.HK", "0883.HK", "0939.HK", "2318.HK",
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
        # 批量 UPSERT（date 字段转 date 对象）
        rows = [
            (symbol, market, _parse_date(r.get("date")), r.get("open"), r.get("high"),
             r.get("low"), r.get("close"), r.get("volume"))
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
