"""分钟 K data pool 维护：旧增量迁移、coverage 重建与月度压实。"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from app.config import settings
from app.db import get_pool
from app.quality import quality_gate

logger = logging.getLogger(__name__)

_MARKETS = ("CN", "HK", "US")
_MARKET_ZONE = {
    "CN": "Asia/Shanghai",
    "HK": "Asia/Hong_Kong",
    "US": "America/New_York",
}


def pool_root() -> Path:
    return Path(settings.DATA_POOL_ROOT)


def baseline_root(market: str) -> Path:
    return pool_root() / "bars" / "minute" / "asset=stock" / f"market={market}"


def baseline_path(market: str, symbol: str, year: int) -> Path:
    return baseline_root(market) / f"symbol={symbol}" / f"year={year}.parquet"


def delta_path(market: str, day: date) -> Path:
    return (
        pool_root()
        / "bars"
        / "minute_delta"
        / "asset=stock"
        / f"market={market}"
        / f"year={day.year}"
        / f"date={day.isoformat()}"
        / "part-000.parquet"
    )


def delta_marker_path(path: Path) -> Path:
    return path.with_name("_SUCCESS.json")


def legacy_root() -> Path:
    return pool_root() / "minute_bars"


def _sql_literal(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _source_sql(paths: Iterable[Path], *, priority_start: int = 1) -> str:
    selects = []
    for priority, path in enumerate(paths, priority_start):
        selects.append(
            "SELECT *, "
            f"{priority}::INTEGER AS _pool_priority FROM read_parquet("
            f"{_sql_literal(path)},union_by_name=true,hive_partitioning=false)"
        )
    if not selects:
        raise ValueError("没有可合并的分钟 K 文件")
    return " UNION ALL ".join(selects)


def parquet_row_count(path: Path) -> int:
    import pyarrow.parquet as pq

    return int(pq.read_metadata(path).num_rows)


def parquet_symbols(path: Path) -> set[str]:
    import duckdb

    connection = duckdb.connect()
    try:
        return {
            str(row[0])
            for row in connection.execute(
                "SELECT DISTINCT symbol FROM read_parquet(?,hive_partitioning=false)",
                [str(path)],
            ).fetchall()
            if row[0]
        }
    finally:
        connection.close()


def merge_minute_files(sources: list[Path], target: Path) -> int:
    """把规范分钟文件原子合并到 target；后传 source 覆盖先传 source。"""
    import duckdb

    existing = [path for path in sources if path.exists()]
    if not existing:
        return 0
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".part")
    temporary.unlink(missing_ok=True)
    connection = duckdb.connect()
    try:
        connection.execute("SET memory_limit='1GB'")
        connection.execute("SET threads=2")
        union_sql = _source_sql(existing)
        connection.execute(f"""
            COPY (
                SELECT * EXCLUDE(_pool_priority, _rank)
                FROM (
                    SELECT *, row_number() OVER (
                        PARTITION BY symbol,datetime
                        ORDER BY _pool_priority DESC, source DESC NULLS LAST
                    ) AS _rank
                    FROM ({union_sql})
                )
                WHERE _rank=1
                ORDER BY symbol,datetime
            ) TO {_sql_literal(temporary)}
            (FORMAT PARQUET,COMPRESSION ZSTD,ROW_GROUP_SIZE 122880)
            """)
        rows = int(
            connection.execute(
                "SELECT num_rows FROM parquet_file_metadata(?)", [str(temporary)]
            ).fetchone()[0]
        )
        os.replace(temporary, target)
        return rows
    finally:
        connection.close()
        temporary.unlink(missing_ok=True)


def merge_symbol_deltas(
    sources: list[Path], target: Path, symbol: str
) -> tuple[int, int]:
    """将一个标的的多个日增量压入 symbol/year 基线，并验证零漏键。"""
    import duckdb

    delta_sql = _source_sql(sources)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".compact.part")
    temporary.unlink(missing_ok=True)
    symbol_literal = _sql_literal(symbol)
    connection = duckdb.connect()
    try:
        connection.execute("SET memory_limit='1GB'")
        connection.execute("SET threads=2")
        selects = []
        if target.exists():
            selects.append(
                "SELECT *, 0::INTEGER AS _pool_priority FROM read_parquet("
                f"{_sql_literal(target)},union_by_name=true,hive_partitioning=false)"
            )
        selects.append(f"SELECT * FROM ({delta_sql}) WHERE symbol={symbol_literal}")
        union_sql = " UNION ALL ".join(selects)
        connection.execute(f"""
            COPY (
                SELECT * EXCLUDE(_pool_priority, _rank)
                FROM (
                    SELECT *, row_number() OVER (
                        PARTITION BY symbol,datetime ORDER BY _pool_priority DESC
                    ) AS _rank
                    FROM ({union_sql})
                )
                WHERE _rank=1 ORDER BY symbol,datetime
            ) TO {_sql_literal(temporary)}
            (FORMAT PARQUET,COMPRESSION ZSTD,ROW_GROUP_SIZE 122880)
            """)
        missing = int(connection.execute(f"""
                SELECT count(*) FROM (
                    SELECT symbol,datetime FROM ({delta_sql})
                    WHERE symbol={symbol_literal}
                    EXCEPT
                    SELECT symbol,datetime FROM read_parquet(
                        {_sql_literal(temporary)},hive_partitioning=false
                    )
                )
                """).fetchone()[0])
        if missing:
            raise ValueError(f"{symbol} 压实后仍缺 {missing} 个增量键")
        rows = int(
            connection.execute(
                "SELECT num_rows FROM parquet_file_metadata(?)", [str(temporary)]
            ).fetchone()[0]
        )
        os.replace(temporary, target)
        return rows, missing
    finally:
        connection.close()
        temporary.unlink(missing_ok=True)


def write_delta_marker(path: Path, payload: dict[str, Any]) -> None:
    marker = delta_marker_path(path)
    temporary = marker.with_suffix(".json.part")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n"
    )
    os.replace(temporary, marker)


def read_delta_marker(path: Path) -> dict[str, Any] | None:
    marker = delta_marker_path(path)
    try:
        value = json.loads(marker.read_text())
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _legacy_partition(path: Path) -> tuple[str, date]:
    parts = path.parts
    market = next(
        part.removeprefix("market=") for part in parts if part.startswith("market=")
    )
    day = date.fromisoformat(
        next(part.removeprefix("date=") for part in parts if part.startswith("date="))
    )
    if market not in _MARKETS:
        raise ValueError(f"未知旧分钟市场: {market}")
    return market, day


def _legacy_rows(path: Path, market: str, day: date) -> list[dict[str, Any]]:
    import pyarrow.parquet as pq
    from zoneinfo import ZoneInfo

    zone = ZoneInfo(_MARKET_ZONE[market])
    result = []
    for item in pq.read_table(path).to_pylist():
        symbol = str(item.get("symbol") or "").strip().upper()
        if market == "US" and symbol and not symbol.endswith(".US"):
            symbol = f"{symbol}.US"
        ts = item.get("ts")
        try:
            local_time = datetime.fromtimestamp(int(ts), tz=timezone.utc).astimezone(
                zone
            )
        except (TypeError, ValueError, OverflowError, OSError):
            continue
        if local_time.date() != day or not symbol or item.get("close") is None:
            continue
        result.append(
            {
                "symbol": symbol,
                "market": market,
                "datetime": local_time.replace(tzinfo=None),
                "ts": int(ts),
                "open": item.get("open"),
                "high": item.get("high"),
                "low": item.get("low"),
                "close": item.get("close"),
                "volume": item.get("volume"),
                "amount": item.get("amount"),
                "source": "legacy_findb",
            }
        )
    return result


def _write_rows(path: Path, rows: list[dict[str, Any]], source: str) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    payload = [
        {
            "symbol": row["symbol"],
            "datetime": row["datetime"],
            "open": row.get("open"),
            "high": row.get("high"),
            "low": row.get("low"),
            "close": row.get("close"),
            "volume": row.get("volume"),
            "amount": row.get("amount"),
            "source": source,
        }
        for row in rows
    ]
    table = pa.Table.from_pylist(payload).sort_by(
        [("symbol", "ascending"), ("datetime", "ascending")]
    )
    pq.write_table(table, path, compression="zstd")


async def migrate_legacy_minute_bars() -> dict[str, int]:
    """迁移旧 minute_bars tracked 分区；验证成功后移入 archive。"""
    root = legacy_root()
    files = sorted(root.glob("year=*/market=*/date=*/part-000.parquet"))
    counts = {"files": 0, "rows": 0, "rejected": 0}
    archive_root = pool_root() / "archive" / "minute_bars_legacy"
    for source in files:
        market, day = _legacy_partition(source)
        normalized = _legacy_rows(source, market, day)
        accepted = await quality_gate("minute_bars", normalized, persist=False)
        counts["rejected"] += len(normalized) - len(accepted)
        if not accepted:
            logger.warning("旧分钟分区无有效数据，保留源文件: %s", source)
            continue
        staging = source.with_suffix(".canonical.parquet")
        await asyncio.to_thread(_write_rows, staging, accepted, "legacy_findb")
        target = delta_path(market, day)
        sources = ([target] if target.exists() else []) + [staging]
        await asyncio.to_thread(merge_minute_files, sources, target)
        source_keys = {(row["symbol"], row["datetime"]) for row in accepted}
        target_keys = await asyncio.to_thread(_minute_keys, target, source_keys)
        missing = source_keys - target_keys
        if missing:
            raise ValueError(f"旧分钟分区迁移漏键 {source}: {len(missing)}")
        archive = archive_root / source.relative_to(root)
        archive.parent.mkdir(parents=True, exist_ok=True)
        os.replace(source, archive)
        staging.unlink(missing_ok=True)
        counts["files"] += 1
        counts["rows"] += len(accepted)
        logger.info(
            "旧分钟分区迁移完成: %s -> %s (%d rows)", source, target, len(accepted)
        )
    return counts


def _minute_keys(
    path: Path, candidates: set[tuple[str, datetime]]
) -> set[tuple[str, datetime]]:
    import duckdb

    if not candidates:
        return set()
    symbols = sorted({symbol for symbol, _ in candidates})
    placeholders = ",".join("?" for _ in symbols)
    connection = duckdb.connect()
    try:
        return {
            (str(row[0]), row[1])
            for row in connection.execute(
                f"""
                SELECT symbol,datetime FROM read_parquet(?,hive_partitioning=false)
                WHERE symbol IN ({placeholders})
                """,
                [str(path), *symbols],
            ).fetchall()
        }
    finally:
        connection.close()


def _footer_range(path: Path) -> tuple[int, datetime | None, datetime | None]:
    import pyarrow.parquet as pq

    metadata = pq.read_metadata(path)
    names = metadata.schema.names
    if "datetime" not in names:
        return int(metadata.num_rows), None, None
    column = names.index("datetime")
    minimum = None
    maximum = None
    for index in range(metadata.num_row_groups):
        statistics = metadata.row_group(index).column(column).statistics
        if statistics is None or not statistics.has_min_max:
            continue
        low = (
            statistics.min.as_py()
            if hasattr(statistics.min, "as_py")
            else statistics.min
        )
        high = (
            statistics.max.as_py()
            if hasattr(statistics.max, "as_py")
            else statistics.max
        )
        minimum = low if minimum is None else min(minimum, low)
        maximum = high if maximum is None else max(maximum, high)
    return int(metadata.num_rows), minimum, maximum


async def refresh_minute_coverage(symbols: set[str] | None = None) -> int:
    """以物理 baseline footer 重建股票 1min coverage 水位。"""
    records = []
    for market in _MARKETS:
        for symbol_dir in sorted(baseline_root(market).glob("symbol=*")):
            symbol = symbol_dir.name.removeprefix("symbol=")
            if symbols is not None and symbol not in symbols:
                continue
            rows = 0
            minimum = None
            maximum = None
            for path in sorted(symbol_dir.glob("*.parquet")):
                count, low, high = await asyncio.to_thread(_footer_range, path)
                rows += count
                if low is not None:
                    minimum = low if minimum is None else min(minimum, low)
                if high is not None:
                    maximum = high if maximum is None else max(maximum, high)
            if rows:
                records.append((symbol, minimum, maximum, rows))
    pool = await get_pool()
    async with pool.acquire() as connection:
        await connection.executemany(
            """
            INSERT INTO data_coverage
                (symbol,frequency,start_at,end_at,row_count,source,source_updated_at)
            VALUES ($1,'1min',$2,$3,$4,'findb',NOW())
            ON CONFLICT (symbol,frequency,source) DO UPDATE SET
                start_at=EXCLUDED.start_at,end_at=EXCLUDED.end_at,
                row_count=EXCLUDED.row_count,source_updated_at=NOW()
            """,
            records,
        )
    logger.info("分钟 coverage 物理重建完成: %d symbols", len(records))
    return len(records)


async def seed_delta_markers() -> int:
    """为迁入的历史 delta 生成覆盖标记；完整性按当日日 K 活跃 baseline 判定。"""
    root = pool_root() / "bars" / "minute_delta" / "asset=stock"
    paths = sorted(root.glob("market=*/year=*/date=*/part-000.parquet"))
    baseline_symbols = {
        market: {
            path.name.removeprefix("symbol=")
            for path in baseline_root(market).glob("symbol=*")
            if path.is_dir()
        }
        for market in _MARKETS
    }
    pool = await get_pool()
    written = 0
    async with pool.acquire() as connection:
        for path in paths:
            market, day = _delta_partition(path)
            rows = await connection.fetch(
                "SELECT symbol FROM daily_prices WHERE market=$1 AND date=$2",
                market,
                day,
            )
            expected = {
                (f"{row['symbol']}.US" if market == "US" else row["symbol"])
                for row in rows
            } & baseline_symbols[market]
            actual = await asyncio.to_thread(parquet_symbols, path)
            covered = len(expected & actual)
            coverage = covered / len(expected) if expected else 0.0
            write_delta_marker(
                path,
                {
                    "schema_version": 1,
                    "market": market,
                    "date": day,
                    "expected_symbols": len(expected),
                    "covered_symbols": covered,
                    "symbol_coverage": round(coverage, 6),
                    "rows": await asyncio.to_thread(parquet_row_count, path),
                    "complete": bool(expected) and covered == len(expected),
                    "source": "legacy_migration",
                    "updated_at": datetime.now(timezone.utc),
                },
            )
            written += 1
    return written


async def run_minute_storage_migration_job() -> dict[str, int]:
    logger.info("=== minute storage migration start ===")
    migrated = await migrate_legacy_minute_bars()
    coverage = await refresh_minute_coverage()
    markers = await seed_delta_markers()
    result = {**migrated, "coverage": coverage, "markers": markers}
    logger.info("=== minute storage migration done: %s ===", result)
    return result


def _delta_partition(path: Path) -> tuple[str, date]:
    market = next(
        part.removeprefix("market=")
        for part in path.parts
        if part.startswith("market=")
    )
    day = date.fromisoformat(
        next(
            part.removeprefix("date=")
            for part in path.parts
            if part.startswith("date=")
        )
    )
    return market, day


def _complete_delta_files(through: date) -> dict[tuple[str, int], list[Path]]:
    grouped: dict[tuple[str, int], list[Path]] = defaultdict(list)
    root = pool_root() / "bars" / "minute_delta" / "asset=stock"
    for path in sorted(root.glob("market=*/year=*/date=*/part-000.parquet")):
        market, day = _delta_partition(path)
        marker = read_delta_marker(path)
        if day <= through and marker and marker.get("complete") is True:
            grouped[(market, day.year)].append(path)
    return grouped


async def run_minute_delta_compact_job(through: date | None = None) -> dict[str, int]:
    """将上月及更早的完整 delta 压入 symbol/year baseline。"""
    first_this_month = date.today().replace(day=1)
    cutoff = through or first_this_month - timedelta(days=1)
    grouped = _complete_delta_files(cutoff)
    compacted_files = 0
    compacted_symbols: set[str] = set()
    for (market, year), files in sorted(grouped.items()):
        symbols: set[str] = set()
        for path in files:
            symbols.update(await asyncio.to_thread(parquet_symbols, path))
        logger.info(
            "分钟增量压实 %s/%d: %d days, %d symbols",
            market,
            year,
            len(files),
            len(symbols),
        )
        for index, symbol in enumerate(sorted(symbols), 1):
            await asyncio.to_thread(
                merge_symbol_deltas,
                files,
                baseline_path(market, symbol, year),
                symbol,
            )
            compacted_symbols.add(symbol)
            if index % 500 == 0:
                logger.info(
                    "分钟增量压实 %s/%d: %d/%d symbols",
                    market,
                    year,
                    index,
                    len(symbols),
                )
        for path in files:
            path.unlink()
            delta_marker_path(path).unlink(missing_ok=True)
            compacted_files += 1
            parent = path.parent
            while parent != pool_root() and parent.exists():
                try:
                    parent.rmdir()
                except OSError:
                    break
                parent = parent.parent
    coverage = (
        await refresh_minute_coverage(compacted_symbols) if compacted_symbols else 0
    )
    result = {
        "files": compacted_files,
        "symbols": len(compacted_symbols),
        "coverage": coverage,
    }
    logger.info("=== minute delta compact done: %s ===", result)
    return result
