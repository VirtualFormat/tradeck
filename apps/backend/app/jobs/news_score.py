"""新闻情绪打分 job（L1 关键词法，幂等：只处理未打分的新增行）"""
from __future__ import annotations

import logging

from app.db import get_pool
from app.services.sentiment import score_news

logger = logging.getLogger(__name__)

BATCH_SIZE = 500


async def run_news_score_job() -> int:
    """定时任务：给 sentiment IS NULL 的新闻打分"""
    logger.info("=== news score job start ===")
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, title, summary FROM news_articles
            WHERE sentiment IS NULL
            ORDER BY id DESC
            LIMIT $1
            """,
            BATCH_SIZE,
        )
        if not rows:
            logger.info("=== news score job done: 0 rows ===")
            return 0
        await conn.executemany(
            """
            UPDATE news_articles
            SET sentiment = $2, scored_at = NOW()
            WHERE id = $1
            """,
            [(r["id"], score_news(r["title"], r["summary"])) for r in rows],
        )
    logger.info(f"=== news score job done: {len(rows)} rows ===")
    return len(rows)
