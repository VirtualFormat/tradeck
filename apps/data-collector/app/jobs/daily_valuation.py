"""A 股日级估值：同花顺全市场批量主源，写 PG + 自有 Parquet。"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import date, datetime, timedelta, timezone
from typing import Any

from app.config import settings
from app.datasource import hithink_source
from app.db import get_pool

logger = logging.getLogger(__name__)


def _number(value: Any) -> float | None:
    try:
        result = float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
    return None if result is not None and result != result else result


async def _all_a_share_symbols() -> list[str]:
    symbols: list[str] = []
    offset = 0
    limit = 1000
    while True:
        data = await hithink_source.get_ticker_list(
            "a-share", limit=limit, offset=offset
        )
        if not data:
            return []
        items = data.get("item") or []
        symbols.extend(
            str(item.get("thscode") or "")
            for item in items
            if item.get("thscode")
        )
        if len(items) < limit:
            break
        offset += limit
    return symbols


def _pool_path(year: int) -> str:
    return os.path.join(
        settings.DATA_POOL_ROOT,
        "snapshots",
        "daily_valuation",
        "market=CN",
        f"year={year}.parquet",
    )


async def _merge_pool(rows: list[tuple]) -> None:
    def merge() -> None:
        import duckdb

        target = _pool_path(rows[0][1].year)
        temporary = f"{target}.part"
        os.makedirs(os.path.dirname(target), exist_ok=True)
        connection = duckdb.connect()
        try:
            connection.execute(
                """
                CREATE TABLE incoming (
                    symbol VARCHAR, date DATE, name VARCHAR,
                    pe_ttm DOUBLE, pe_mrq DOUBLE, pb_mrq DOUBLE,
                    ps_ttm DOUBLE, pcf_ttm DOUBLE, source VARCHAR,
                    source_updated_at TIMESTAMPTZ
                )
                """
            )
            connection.executemany(
                "INSERT INTO incoming VALUES (?,?,?,?,?,?,?,?,?,?)", rows
            )
            incoming = "SELECT * FROM incoming"
            if os.path.exists(target):
                escaped = target.replace("'", "''")
                incoming = f"""
                    SELECT symbol,date,name,pe_ttm,pe_mrq,pb_mrq,ps_ttm,pcf_ttm,
                           source,source_updated_at
                    FROM (
                        SELECT *, row_number() OVER (
                            PARTITION BY symbol,date ORDER BY priority DESC
                        ) rank
                        FROM (
                            SELECT *, 1 priority
                            FROM read_parquet('{escaped}',hive_partitioning=false)
                            UNION ALL BY NAME
                            SELECT *, 2 priority FROM incoming
                        )
                    ) WHERE rank=1
                """
            out = temporary.replace("'", "''")
            connection.execute(
                f"COPY (SELECT * FROM ({incoming}) ORDER BY symbol,date) "
                f"TO '{out}' (FORMAT PARQUET,COMPRESSION ZSTD,ROW_GROUP_SIZE 122880)"
            )
            os.replace(temporary, target)
        finally:
            connection.close()
            if os.path.exists(temporary):
                os.remove(temporary)

    await asyncio.to_thread(merge)


async def run_daily_valuation_job() -> int:
    logger.info("=== daily valuation job start ===")
    symbols = await _all_a_share_symbols()
    if not symbols:
        logger.warning("hithink A股代码表为空，估值任务跳过")
        return 0

    items: list[dict[str, Any]] = []
    for offset in range(0, len(symbols), 100):
        batch = await hithink_source.get_valuations_snapshot(
            symbols[offset : offset + 100]
        )
        items.extend(batch)
        await asyncio.sleep(0.05)
    if not items:
        return 0

    # 正常亏损/指标缺失的股票也可能不返回，不按空批次数判失败；要求整体覆盖率
    # 至少 60%，否则保留上一日完整快照。
    unique_returned = {str(item.get("thscode")) for item in items}
    if len(unique_returned) < int(len(symbols) * 0.6):
        logger.warning(
            "hithink 估值覆盖不足: %d/%d，不发布不完整快照",
            len(unique_returned),
            len(symbols),
        )
        return 0

    now = datetime.now(timezone.utc)

    def source_date(item: dict[str, Any]) -> date:
        from zoneinfo import ZoneInfo

        timestamp = item.get("_source_timestamp")
        if timestamp:
            try:
                return datetime.fromtimestamp(
                    int(timestamp) / 1000, tz=ZoneInfo("Asia/Shanghai")
                ).date()
            except (TypeError, ValueError, OverflowError, OSError):
                pass
        # 无上游时间才降级到最近工作日。
        fallback = date.today()
        if fallback.weekday() == 5:
            fallback -= timedelta(days=1)
        elif fallback.weekday() == 6:
            fallback -= timedelta(days=2)
        return fallback
    rows = [
        (
            str(item["thscode"]),
            source_date(item),
            str(item.get("name") or "") or None,
            _number(item.get("pe_ttm")),
            _number(item.get("pe_mrq")),
            _number(item.get("pb_mrq")),
            _number(item.get("ps_ttm")),
            _number(item.get("pcf_ttm")),
            "hithink",
            now,
        )
        for item in items
        if item.get("thscode")
    ]

    pool = await get_pool()
    async with pool.acquire() as connection:
        await connection.executemany(
            """
            INSERT INTO daily_valuations
                (symbol,date,name,pe_ttm,pe_mrq,pb_mrq,ps_ttm,pcf_ttm,
                 source,source_updated_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
            ON CONFLICT (symbol,date) DO UPDATE SET
                name=EXCLUDED.name, pe_ttm=EXCLUDED.pe_ttm,
                pe_mrq=EXCLUDED.pe_mrq, pb_mrq=EXCLUDED.pb_mrq,
                ps_ttm=EXCLUDED.ps_ttm, pcf_ttm=EXCLUDED.pcf_ttm,
                source=EXCLUDED.source,
                source_updated_at=EXCLUDED.source_updated_at
            """,
            rows,
        )
    await _merge_pool(rows)
    logger.info("=== daily valuation job done: %d rows ===", len(rows))
    return len(rows)
