"""数据清理（TTL，定期删除过期数据）"""
from __future__ import annotations

import logging

from app.db import get_pool

logger = logging.getLogger(__name__)


async def run_cleanup_job() -> None:
    """定时任务：清理过期数据

    - news_articles：保留 30 天
    - quote_snapshots：保留 7 天（不活跃的 symbol）
    - movers_cache：保留当天（job 会全量覆盖，不需要清理）
    - daily_prices / index_prices / macro_indicators：永久保留（历史数据）
    - income_statements / equity_profiles / fundamental_metrics：永久保留
    """
    logger.info("=== cleanup job start ===")
    pool = await get_pool()
    async with pool.acquire() as conn:
        # 新闻：保留 30 天
        deleted_news = await conn.execute(
            "DELETE FROM news_articles WHERE fetched_at < NOW() - INTERVAL '30 days'"
        )
        logger.info(f"deleted {deleted_news} old news articles")

        # 报价快照：保留 7 天不活跃的
        deleted_quotes = await conn.execute(
            "DELETE FROM quote_snapshots WHERE updated_at < NOW() - INTERVAL '7 days'"
        )
        logger.info(f"deleted {deleted_quotes} stale quote snapshots")

    logger.info("=== cleanup job done ===")
