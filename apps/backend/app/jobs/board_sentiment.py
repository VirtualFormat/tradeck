"""板块舆情热度聚合 job

聚合：symbol_board_map × news_articles(24h, 已打分) → board_sentiment
hot_score = 0.6 × 行情热度（|change_percent|/3 截断）+ 0.4 × 舆情热度（情绪归一 × 新闻量对数归一）
"""
from __future__ import annotations

import logging
import math

from app.db import get_pool

logger = logging.getLogger(__name__)

# 新闻量归一化基准（log(1+N)，N=20 时热度记为满分）
NEWS_COUNT_NORM = 20


async def run_board_sentiment_job() -> None:
    """定时任务：聚合板块舆情热度"""
    logger.info("=== board sentiment job start ===")
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT m.board_type, m.board_name,
                   count(DISTINCT a.url) AS news_count,
                   avg(a.sentiment) AS sentiment_avg
            FROM symbol_board_map m
            JOIN news_articles a ON a.symbol = m.symbol AND a.sentiment IS NOT NULL
            WHERE a.published_at > NOW() - interval '24 hours'
            GROUP BY m.board_type, m.board_name
            """
        )
        if not rows:
            logger.info("=== board sentiment job done: 0 rows ===")
            return

        # 关联行情热度
        heat_rows = await conn.fetch(
            "SELECT board_type, name, change_percent FROM board_heat"
        )
        heat = {(h["board_type"], h["name"]): h["change_percent"] for h in heat_rows}

        out = []
        for r in rows:
            key = (r["board_type"], r["board_name"])
            change = heat.get(key)
            heat_score = min(abs(float(change)) / 3.0, 1.0) if change is not None else 0.0
            sentiment_norm = (float(r["sentiment_avg"] or 0) + 1.0) / 2.0
            count_norm = math.log1p(r["news_count"]) / math.log1p(NEWS_COUNT_NORM)
            hot = 0.6 * heat_score + 0.4 * sentiment_norm * count_norm
            out.append((
                r["board_type"],
                r["board_name"],
                r["news_count"],
                round(float(r["sentiment_avg"] or 0), 3),
                round(hot, 3),
            ))

        await conn.executemany(
            """
            INSERT INTO board_sentiment
                (board_type, board_name, news_count_24h, sentiment_avg, hot_score,
                 snapshot_date, updated_at)
            VALUES ($1, $2, $3, $4, $5, CURRENT_DATE, NOW())
            ON CONFLICT (board_type, board_name, snapshot_date) DO UPDATE SET
                news_count_24h = EXCLUDED.news_count_24h,
                sentiment_avg = EXCLUDED.sentiment_avg,
                hot_score = EXCLUDED.hot_score,
                updated_at = NOW()
            """,
            out,
        )
    logger.info(f"=== board sentiment job done: {len(out)} rows ===")
