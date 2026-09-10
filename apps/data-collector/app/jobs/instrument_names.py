"""证券中文名称同步：同花顺全市场 A 股标的列表 → instrument_master + quote_snapshots 回填。

修复 quant 精确涨跌停的 ST ±5% 判定空转：数据底座此前无 A 股中文名
（quote_snapshots.name 为 null、equity_profiles 存英文名），本 job 从同花顺
meta/tickers/list 拉全量中文简称，UPSERT 进 instrument_master，并回填
quote_snapshots.name（仅 name IS NULL 的行），下游 quant _fetch_names 读
quote_snapshots 即自动贯通，无需改动。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.datasource import hithink_source
from app.db import get_pool

logger = logging.getLogger(__name__)

_PAGE_SIZE = 1000
# 单页失败额外重试次数（hithink_get 内部还有退避重试，此处为页级兜底）
_PAGE_RETRIES = 2
# 翻页限速：外部源，避免触发限流
_PAGE_INTERVAL = 0.3


async def _fetch_all_a_share() -> list[dict[str, Any]]:
    """翻页拉全量 A 股标的列表；单页失败重试 _PAGE_RETRIES 次后跳过继续。"""
    items: list[dict[str, Any]] = []
    offset = 0
    while True:
        data = None
        for attempt in range(_PAGE_RETRIES + 1):
            data = await hithink_source.get_ticker_list(
                "a-share", limit=_PAGE_SIZE, offset=offset
            )
            if data is not None:
                break
            logger.warning(
                "同花顺标的列表第 %d 页获取失败（第 %d 次）",
                offset // _PAGE_SIZE,
                attempt + 1,
            )
            await asyncio.sleep(1.0)
        if data is None:
            # 整页失败：跳过该页继续，避免整体空转
            offset += _PAGE_SIZE
            continue
        page = data.get("item") or []
        items.extend(page)
        if len(page) < _PAGE_SIZE:
            break
        offset += _PAGE_SIZE
        await asyncio.sleep(_PAGE_INTERVAL)
    return items


async def run_instrument_names_job() -> int:
    """同步全市场 A 股中文名：instrument_master UPSERT + quote_snapshots 回填。"""
    logger.info("=== instrument_names job start ===")
    try:
        items = await _fetch_all_a_share()
    except Exception:  # noqa: BLE001 - 优雅降级：外部源异常不抛出
        logger.exception("instrument_names 拉取标的列表异常")
        return 0

    rows = [
        (
            str(item["thscode"]),
            str(item.get("name") or "").strip() or None,
        )
        for item in items
        if item.get("thscode")
    ]
    # 去重（同一 symbol 保留非空名称）
    dedup: dict[str, str | None] = {}
    for symbol, name in rows:
        if symbol not in dedup or (name and not dedup[symbol]):
            dedup[symbol] = name
    rows = sorted(dedup.items())
    if not rows:
        logger.warning("同花顺 A 股标的列表为空，instrument_names 跳过")
        return 0

    pool = await get_pool()
    async with pool.acquire() as connection:
        async with connection.transaction():
            await connection.executemany(
                """
                INSERT INTO instrument_master
                    (symbol, name, asset, market, source, source_updated_at)
                VALUES ($1, $2, 'stock', 'CN', 'hithink', NOW())
                ON CONFLICT (symbol, source) DO UPDATE SET
                    name = EXCLUDED.name,
                    asset = EXCLUDED.asset,
                    market = EXCLUDED.market,
                    source_updated_at = EXCLUDED.source_updated_at
                """,
                rows,
            )
            # 回填存量报价快照的中文名（只补空名，不覆盖其他源已写入的名称）
            backfilled = await connection.execute(
                """
                UPDATE quote_snapshots AS q
                SET name = v.name
                FROM (
                    SELECT * FROM unnest($1::text[], $2::text[])
                ) AS v(symbol, name)
                WHERE q.symbol = v.symbol
                  AND q.name IS NULL
                  AND v.name IS NOT NULL
                """,
                [symbol for symbol, _ in rows],
                [name for _, name in rows],
            )
    backfill_count = int(backfilled.split()[-1]) if backfilled else 0
    logger.info(
        "=== instrument_names job done: %d rows ===（quote_snapshots 回填 %d 行）",
        len(rows),
        backfill_count,
    )
    return len(rows)
