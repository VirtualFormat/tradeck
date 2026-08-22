"""A 股新闻采集（东财个股新闻，直调 akshare，写入 news_articles）"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.datasource import call_akshare
from app.db import get_pool
from app.constants import TRACKED_SYMBOLS
from app.markets import pick_market

logger = logging.getLogger(__name__)
SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


def _parse_time(s: object) -> datetime | None:
    """东财时间格式：2026-07-19 12:30:00"""
    if not s:
        return None
    try:
        # 东财发布时间是中国本地时间；先赋上海时区，再统一转 UTC 入库。
        return (
            datetime.strptime(str(s)[:19], "%Y-%m-%d %H:%M:%S")
            .replace(tzinfo=SHANGHAI_TZ)
            .astimezone(timezone.utc)
        )
    except (ValueError, TypeError):
        return None


async def fetch_and_store_akshare_news(symbol: str) -> int:
    """拉单只 A 股的东财新闻，UPSERT。返回新增/更新条数。"""
    import akshare as ak

    code = symbol.split(".")[0]

    def fetch():
        return ak.stock_news_em(symbol=code)

    try:
        df = await call_akshare(fetch)
    except Exception as e:
        logger.warning(f"akshare news failed for {symbol}: {e}")
        return 0
    if df is None or df.empty:
        return 0

    rows = []
    for _, r in df.iterrows():
        title = str(r.get("新闻标题") or "").strip()
        url = str(r.get("新闻链接") or "").strip()
        if not title or not url:
            continue
        rows.append((
            symbol,
            title,
            url,
            str(r.get("新闻内容") or "")[:2000] or None,
            str(r.get("文章来源") or "") or None,
            _parse_time(r.get("发布时间")),
        ))
    if not rows:
        return 0

    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.executemany(
            """
            INSERT INTO news_articles (symbol, title, url, summary, publisher, published_at)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (url) DO UPDATE SET
                symbol = EXCLUDED.symbol,
                title = EXCLUDED.title,
                summary = EXCLUDED.summary,
                publisher = EXCLUDED.publisher,
                published_at = EXCLUDED.published_at,
                fetched_at = NOW()
            """,
            rows,
        )
    return len(rows)


async def run_akshare_news_job() -> int:
    """定时任务：拉 30 只 A 股跟踪标的的东财新闻（限流交给数据层门面）"""
    logger.info("=== akshare news job start ===")
    total = 0
    for symbol in TRACKED_SYMBOLS:
        if pick_market(symbol) != "CN":
            continue
        total += await fetch_and_store_akshare_news(symbol)
    logger.info(f"=== akshare news job done: {total} rows ===")
    return total
