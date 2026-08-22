"""分析师共识/目标价（调 OpenBB yfinance estimates，写入 analyst_consensus 按日快照）"""
from __future__ import annotations

import logging
from datetime import date

from app.db import get_pool
from app.constants import TRACKED_SYMBOLS
from app.markets import to_yahoo_symbol
from app.openbb_client import fetch_openbb

logger = logging.getLogger(__name__)


async def fetch_and_store_consensus(symbol: str, snapshot_date: date) -> int:
    """拉单只标的的分析师共识，UPSERT 写入 analyst_consensus。返回写入条数。"""
    data = await fetch_openbb(
        "/equity/estimates/consensus",
        {"provider": "yfinance", "symbol": to_yahoo_symbol(symbol)},
    )
    results = data.get("results", [])
    if not results:
        # A 股/港股标的 yfinance 常无共识数据，跳过即可
        return 0

    r = results[0]
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO analyst_consensus
                (symbol, snapshot_date, recommendation, recommendation_mean,
                 number_of_analysts, target_high, target_low, target_consensus,
                 target_median, current_price, currency, fetched_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, NOW())
            ON CONFLICT (symbol, snapshot_date) DO UPDATE SET
                recommendation = EXCLUDED.recommendation,
                recommendation_mean = EXCLUDED.recommendation_mean,
                number_of_analysts = EXCLUDED.number_of_analysts,
                target_high = EXCLUDED.target_high,
                target_low = EXCLUDED.target_low,
                target_consensus = EXCLUDED.target_consensus,
                target_median = EXCLUDED.target_median,
                current_price = EXCLUDED.current_price,
                currency = EXCLUDED.currency,
                fetched_at = NOW()
            """,
            symbol,
            snapshot_date,
            r.get("recommendation"),
            float(r["recommendation_mean"]) if r.get("recommendation_mean") is not None else None,
            int(r["number_of_analysts"]) if r.get("number_of_analysts") is not None else None,
            float(r["target_high"]) if r.get("target_high") is not None else None,
            float(r["target_low"]) if r.get("target_low") is not None else None,
            float(r["target_consensus"]) if r.get("target_consensus") is not None else None,
            float(r["target_median"]) if r.get("target_median") is not None else None,
            float(r["current_price"]) if r.get("current_price") is not None else None,
            r.get("currency"),
        )
    return 1


async def run_analyst_consensus_job() -> int:
    """定时任务：拉所有跟踪股票的分析师共识（每天一次）"""
    logger.info("=== analyst consensus job start ===")
    today = date.today()
    total = 0
    for symbol in TRACKED_SYMBOLS:
        total += await fetch_and_store_consensus(symbol, today)
    logger.info(f"=== analyst consensus job done: {total} rows ===")
    return total
