"""A 股板块热度：同花顺指数目录 + 批量快照，findb 兜底。"""
from __future__ import annotations

import asyncio
import logging
from datetime import date
from typing import Any

from app.datasource import findb_source, hithink_source
from app.db import get_pool
from app.quality import quality_gate

logger = logging.getLogger(__name__)


def _f(value: Any) -> float | None:
    try:
        result = float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
    return None if result is not None and result != result else result


async def _hithink_rows(board_type: str) -> list[tuple]:
    """同花顺主源：目录一次全量 + 快照 100 只/批。"""
    tag = "industry" if board_type == "industry" else "cn_concept"
    boards = await hithink_source.get_index_catalog(tag)
    if not boards:
        return []
    codes = [str(item.get("thscode") or "") for item in boards]
    snapshots: dict[str, dict] = {}
    failed_batches = 0
    for offset in range(0, len(codes), 100):
        items = await hithink_source.get_index_snapshot(codes[offset : offset + 100])
        if not items:
            failed_batches += 1
        snapshots.update(
            (str(item.get("thscode") or ""), item)
            for item in items
            if item.get("thscode")
        )
    if failed_batches or len(snapshots) < int(len(codes) * 0.8):
        logger.warning(
            "hithink %s boards snapshot incomplete: %d/%d, fallback findb",
            board_type,
            len(snapshots),
            len(codes),
        )
        return []
    result = []
    for board in boards:
        code = str(board.get("thscode") or "")
        name = str(board.get("name") or "").strip()
        if not code or not name:
            continue
        snapshot = snapshots.get(code, {})
        result.append(
            (
                board_type,
                name,
                code,
                _f(snapshot.get("price_change_ratio_pct")),
                None,
                _f(snapshot.get("turnover_rate")),
                None,
                None,
            )
        )
    logger.info("hithink %s boards: %d", board_type, len(result))
    return result


async def _findb_concept_rows() -> list[tuple]:
    boards = await findb_source.fetch_table(
        "ths_index", cols="ts_code,name", col="type", val="N", limit=5000
    )
    if not boards:
        return []
    latest: dict[str, dict] = {}

    async def fetch_one(code: str) -> None:
        items = await findb_source.fetch_table(
            "ths_index_daily",
            cols="ts_code,pct_change,turnover_rate",
            col="ts_code",
            val=code,
            sort="trade_date",
            order="desc",
            limit=1,
        )
        if items:
            latest[code] = items[0]

    codes = [str(item.get("ts_code") or "") for item in boards]
    for offset in range(0, len(codes), 5):
        await asyncio.gather(*(fetch_one(code) for code in codes[offset : offset + 5]))
        await asyncio.sleep(0.2)

    result = []
    for board in boards:
        code = str(board.get("ts_code") or "")
        name = str(board.get("name") or "").strip()
        if not code or not name:
            continue
        snapshot = latest.get(code, {})
        result.append(
            (
                "concept",
                name,
                code,
                _f(snapshot.get("pct_change")),
                None,
                _f(snapshot.get("turnover_rate")),
                None,
                None,
            )
        )
    return result


async def _findb_industry_rows() -> list[tuple]:
    boards = await findb_source.fetch_table(
        "sw_industry", cols="index_code,industry_name", limit=5000
    )
    return [
        (
            "industry",
            str(item["industry_name"]),
            str(item["index_code"]),
            None,
            None,
            None,
            None,
            None,
        )
        for item in boards
        if item.get("index_code") and item.get("industry_name")
    ]


async def fetch_and_store_boards(board_type: str) -> int:
    rows = await _hithink_rows(board_type)
    if not rows:
        logger.warning("hithink %s boards empty, fallback to findb", board_type)
        rows = (
            await _findb_industry_rows()
            if board_type == "industry"
            else await _findb_concept_rows()
        )
    if not rows:
        logger.warning("No boards data for %s", board_type)
        return 0

    columns = (
        "board_type",
        "name",
        "code",
        "change_percent",
        "market_cap",
        "turnover_rate",
        "leader_stock",
        "leader_change",
    )
    today = date.today()
    accepted = await quality_gate(
        "board_heat",
        [{**dict(zip(columns, row)), "snapshot_date": today} for row in rows],
    )
    if not accepted:
        return 0
    stored = [tuple(item[column] for column in columns) for item in accepted]
    pool = await get_pool()
    async with pool.acquire() as connection:
        async with connection.transaction():
            await connection.execute(
                "DELETE FROM board_heat WHERE board_type=$1 "
                "AND snapshot_date=CURRENT_DATE",
                board_type,
            )
            await connection.executemany(
                """
                INSERT INTO board_heat
                    (board_type, name, code, change_percent, market_cap,
                     turnover_rate, leader_stock, leader_change, updated_at)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,NOW())
                """,
                stored,
            )
    return len(stored)


async def run_board_heat_job() -> dict[str, int]:
    logger.info("=== board heat job start ===")
    counts = {
        "concept": await fetch_and_store_boards("concept"),
        "industry": await fetch_and_store_boards("industry"),
    }
    logger.info("=== board heat job done: %d rows ===", sum(counts.values()))
    return counts
