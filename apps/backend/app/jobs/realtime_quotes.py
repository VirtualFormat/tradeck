"""盘中轮询报价（调 OpenBB quote，写入 quote_snapshots）"""
from __future__ import annotations

import logging

from app.db import get_pool
from app.jobs.daily_kline import TRACKED_SYMBOLS
from app.markets import pick_market, pick_provider
from app.openbb_client import fetch_openbb

logger = logging.getLogger(__name__)


async def fetch_and_store_quotes(symbols: list[str]) -> int:
    """批量拉报价，写入 quote_snapshots。返回写入条数。"""
    # 按 provider 分组
    akshare_syms = [s for s in symbols if pick_provider(s) == "akshare"]
    yfinance_syms = [s for s in symbols if pick_provider(s) == "yfinance"]

    all_quotes: list[dict] = []

    if akshare_syms:
        data = await fetch_openbb(
            "/equity/price/quote",
            {"provider": "akshare", "symbol": ",".join(akshare_syms)},
        )
        all_quotes.extend(data.get("results", []))

    if yfinance_syms:
        data = await fetch_openbb(
            "/equity/price/quote",
            {"provider": "yfinance", "symbol": ",".join(yfinance_syms)},
        )
        all_quotes.extend(data.get("results", []))

    if not all_quotes:
        logger.warning("No quotes fetched")
        return 0

    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = [
            (
                q.get("symbol"),
                q.get("name"),
                q.get("last_price"),
                q.get("change"),
                q.get("change_percent"),
                q.get("volume"),
                pick_market(q.get("symbol", "")),
            )
            for q in all_quotes
            if q.get("symbol")
        ]
        await conn.executemany(
            """
            INSERT INTO quote_snapshots
                (symbol, name, last_price, change, change_percent, volume, market, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, NOW())
            ON CONFLICT (symbol) DO UPDATE SET
                name = EXCLUDED.name,
                last_price = EXCLUDED.last_price,
                -- yfinance 常返回 null 涨跌，保留已有值避免清掉有效数据
                change = COALESCE(EXCLUDED.change, quote_snapshots.change),
                change_percent = COALESCE(EXCLUDED.change_percent, quote_snapshots.change_percent),
                volume = EXCLUDED.volume,
                market = EXCLUDED.market,
                updated_at = NOW()
            """,
            rows,
        )
    logger.info(f"fetched {len(all_quotes)} quotes")
    return len(all_quotes)


async def run_realtime_quotes_job() -> None:
    """定时任务：轮询所有跟踪股票报价"""
    logger.info("=== realtime quotes job start ===")
    count = await fetch_and_store_quotes(TRACKED_SYMBOLS)
    logger.info(f"=== realtime quotes job done: {count} rows ===")
