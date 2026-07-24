"""涨跌榜（调 OpenBB discovery，缓存到 DB）"""
from __future__ import annotations

import logging
from datetime import date, timedelta

from app.db import get_pool
from app.openbb_client import fetch_openbb

logger = logging.getLogger(__name__)


async def fetch_and_store_movers() -> int:
    """拉涨跌榜 + 活跃榜，写入 movers_cache。返回总条数。"""
    total = 0
    for mover_type in ["gainers", "losers", "active"]:
        data = await fetch_openbb(
            f"/equity/discovery/{mover_type}",
            {"provider": "yfinance"},
        )
        results = data.get("results", [])
        if not results:
            continue

        pool = await get_pool()
        async with pool.acquire() as conn:
            # 只删当天快照（保留历史日期，供回看）
            await conn.execute(
                "DELETE FROM movers_cache WHERE type = $1 AND snapshot_date = CURRENT_DATE",
                mover_type,
            )
            # 批量插入
            rows = [
                (
                    mover_type,
                    "US",  # yfinance discovery 主要是美股
                    i + 1,
                    r.get("symbol"),
                    r.get("name"),
                    r.get("price"),
                    r.get("percent_change"),
                    r.get("volume"),
                )
                for i, r in enumerate(results[:20])
            ]
            if rows:
                await conn.executemany(
                    """
                    INSERT INTO movers_cache
                        (type, market, rank, symbol, name, price, percent_change, volume, updated_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW())
                    """,
                    rows,
                )
                total += len(rows)
        logger.info(f"fetched {len(results)} {mover_type}")
    logger.info(f"=== movers job done: {total} rows ===")
    return total


async def run_movers_job() -> None:
    """定时任务：拉涨跌榜"""
    logger.info("=== movers job start ===")
    await fetch_and_store_movers()
