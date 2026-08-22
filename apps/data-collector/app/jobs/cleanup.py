"""数据清理（TTL，定期删除过期数据）"""
from __future__ import annotations

import logging

from app.db import get_pool

logger = logging.getLogger(__name__)


def _deleted_count(command_tag: str) -> int:
    try:
        return int(command_tag.rsplit(" ", 1)[-1])
    except (TypeError, ValueError):
        return 0


async def run_cleanup_job() -> dict[str, int]:
    """定时任务：清理过期数据

    - news_articles：保留 30 天
    - quote_snapshots：保留 7 天（不活跃的 symbol）
    - 快照表（movers_cache / fund_flow / board_heat / board_sentiment / analyst_consensus）：保留 30 天
    - announcements / research_reports：保留 180 天
    - market_breadth：保留 730 天
    - data_quality_rejects / data_quality_metrics：保留 90 天（质量层留痕与度量）
    - daily_prices / index_prices / macro_indicators：永久保留（历史数据）
    - income_statements / equity_profiles / fundamental_metrics / balance_sheets / cash_flow_statements：永久保留
    """
    logger.info("=== cleanup job start ===")
    counts: dict[str, int] = {}
    pool = await get_pool()
    async with pool.acquire() as conn:
        # 新闻：保留 30 天
        deleted_news = await conn.execute(
            "DELETE FROM news_articles WHERE fetched_at < NOW() - INTERVAL '30 days'"
        )
        counts["news_articles"] = _deleted_count(deleted_news)
        logger.info(f"deleted {deleted_news} old news articles")

        # 报价快照：保留 7 天不活跃的
        deleted_quotes = await conn.execute(
            "DELETE FROM quote_snapshots WHERE updated_at < NOW() - INTERVAL '7 days'"
        )
        counts["quote_snapshots"] = _deleted_count(deleted_quotes)
        logger.info(f"deleted {deleted_quotes} stale quote snapshots")

        # 五类快照表：保留 30 天（fund_flow 每日数千行，必须 TTL）
        for table in ("movers_cache", "fund_flow", "board_heat", "board_sentiment", "analyst_consensus"):
            deleted = await conn.execute(
                f"DELETE FROM {table} WHERE snapshot_date < CURRENT_DATE - INTERVAL '30 days'"
            )
            counts[table] = _deleted_count(deleted)
            logger.info(f"deleted {deleted} old snapshots from {table}")

        # 公告 / 研报：保留 180 天
        for table in ("announcements", "research_reports"):
            deleted = await conn.execute(
                f"DELETE FROM {table} WHERE publish_date < CURRENT_DATE - INTERVAL '180 days'"
            )
            counts[table] = _deleted_count(deleted)
            logger.info(f"deleted {deleted} old rows from {table}")

        # 市场宽度：保留 730 天
        deleted_breadth = await conn.execute(
            "DELETE FROM market_breadth WHERE date < CURRENT_DATE - INTERVAL '730 days'"
        )
        counts["market_breadth"] = _deleted_count(deleted_breadth)
        logger.info(f"deleted {deleted_breadth} old rows from market_breadth")

        # 数据质量层：quarantine 留痕与质量度量均保留 90 天
        # （拒绝样本有审计价值，比榜单类 30 天略长；度量是聚合行，量极小）
        deleted_rejects = await conn.execute(
            "DELETE FROM data_quality_rejects WHERE rejected_at < NOW() - INTERVAL '90 days'"
        )
        counts["data_quality_rejects"] = _deleted_count(deleted_rejects)
        logger.info(f"deleted {deleted_rejects} old rows from data_quality_rejects")

        deleted_dq_metrics = await conn.execute(
            "DELETE FROM data_quality_metrics WHERE date < CURRENT_DATE - INTERVAL '90 days'"
        )
        counts["data_quality_metrics"] = _deleted_count(deleted_dq_metrics)
        logger.info(f"deleted {deleted_dq_metrics} old rows from data_quality_metrics")

    logger.info("=== cleanup job done ===")
    return counts
