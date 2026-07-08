"""新闻（调 OpenBB news/company，写入 news_articles）"""
from __future__ import annotations

import logging
from datetime import date, timedelta

from app.db import get_pool
from app.openbb_client import fetch_openbb

logger = logging.getLogger(__name__)

# 新闻跟踪的 symbol（热门股 + ADR）
NEWS_SYMBOLS = [
    "AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "GOOGL", "META", "NFLX",
    "AMD", "JPM", "BAC", "V", "MA", "WMT", "DIS", "XOM",
    "BABA", "PDD", "JD", "BIDU", "NIO", "XPEV", "LI",
]


async def fetch_and_store_news(symbol: str, limit: int = 10) -> int:
    """拉单只股票新闻，写入 DB。返回写入条数。"""
    data = await fetch_openbb(
        "/news/company",
        {"provider": "yfinance", "symbol": symbol, "limit": limit},
    )
    results = data.get("results", [])
    if not results:
        logger.warning(f"No news for {symbol}")
        return 0

    pool = await get_pool()
    async with pool.acquire() as conn:
        for r in results:
            url = r.get("url")
            if not url:
                continue
            try:
                pub_date = r.get("date")
                if pub_date:
                    from datetime import datetime
                    dt = datetime.fromisoformat(pub_date.replace("Z", "+00:00"))
                else:
                    dt = None
            except Exception:
                dt = None

            await conn.execute(
                """
                INSERT INTO news_articles (symbol, title, url, summary, publisher, published_at)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (url) DO NOTHING
                """,
                symbol,
                r.get("title", ""),
                url,
                r.get("summary"),
                r.get("publisher") or r.get("source"),
                dt,
            )
    logger.info(f"fetched {len(results)} news for {symbol}")
    return len(results)


async def run_news_job() -> None:
    """定时任务：拉所有新闻"""
    logger.info("=== news job start ===")
    total = 0
    for symbol in NEWS_SYMBOLS:
        count = await fetch_and_store_news(symbol, 10)
        total += count
    logger.info(f"=== news job done: {total} articles ===")
