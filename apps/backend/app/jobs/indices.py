"""指数历史（调 OpenBB index/historical，写入 index_prices）"""
from __future__ import annotations

import logging
from datetime import date, timedelta

from app.db import get_pool
from app.openbb_client import fetch_openbb

logger = logging.getLogger(__name__)


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except Exception:
        return None


# 跟踪的指数
TRACKED_INDICES = [
    {"symbol": "^GSPC", "market": "US"},
    {"symbol": "^IXIC", "market": "US"},
    {"symbol": "^DJI", "market": "US"},
    {"symbol": "^HSI", "market": "HK"},
    {"symbol": "^HSCEI", "market": "HK"},
    {"symbol": "000001.SS", "market": "CN"},
    {"symbol": "399001.SZ", "market": "CN"},
    {"symbol": "399006.SZ", "market": "CN"},
]

# 大宗商品（用 index/historical 拉）
TRACKED_COMMODITIES = [
    {"symbol": "GC=F", "market": "US"},  # 黄金
    {"symbol": "CL=F", "market": "US"},  # 原油
    {"symbol": "SI=F", "market": "US"},  # 白银
    {"symbol": "BTC-USD", "market": "US"},  # 比特币
]


async def fetch_and_store_index(symbol: str, market: str) -> int:
    """拉单只指数历史，写入 DB。返回写入条数。"""
    end = date.today().isoformat()
    start = (date.today() - timedelta(days=30)).isoformat()

    data = await fetch_openbb(
        "/index/price/historical",
        {
            "provider": "yfinance",
            "symbol": symbol,
            "start_date": start,
            "end_date": end,
        },
    )
    results = data.get("results", [])
    if not results:
        logger.warning(f"No index data for {symbol}")
        return 0

    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = [
            (symbol, market, _parse_date(r.get("date")), r.get("close"), r.get("volume"))
            for r in results
        ]
        await conn.executemany(
            """
            INSERT INTO index_prices (symbol, market, date, close, volume)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (symbol, date) DO UPDATE SET
                close = EXCLUDED.close, volume = EXCLUDED.volume
            """,
            rows,
        )
    logger.info(f"fetched {len(results)} index prices for {symbol}")
    return len(results)


async def run_indices_job() -> None:
    """定时任务：拉所有指数历史"""
    logger.info("=== indices job start ===")
    total = 0
    for idx in TRACKED_INDICES + TRACKED_COMMODITIES:
        count = await fetch_and_store_index(idx["symbol"], idx["market"])
        total += count
    logger.info(f"=== indices job done: {total} rows ===")
