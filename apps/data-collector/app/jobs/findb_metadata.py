"""findb core 一次性初始化：供应商格式 → tradeck 自有 data pool。

COS 的 ``core.duckdb.zst`` 只作为初始化输入，解压到 staging 后立即清洗：
- 5275 万行复权因子转成按年分区、字段规范化的 ZSTD Parquet；
- instruments/coverage/更名/停牌转成规范化 Parquet，并镜像 PostgreSQL 热层；
- 原始 zst/DuckDB 在发布成功后删除，不作为运行时依赖。

任务只登记到手动任务白名单，不注册 APScheduler，也不参加启动预热。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from app.config import settings
from app.datasource import findb_archive_source
from app.db import get_pool

logger = logging.getLogger(__name__)

_CORE_FILE = "core.duckdb.zst"
_POOL_SCHEMA_VERSION = 1
_HOT_TABLES: dict[str, tuple[str, ...]] = {
    "symbols": ("code", "name", "asset", "market", "type", "updated_at"),
    "coverage": ("code", "freq", "start_dt", "end_dt", "rows", "updated_at"),
    "stk_namechange": (
        "ts_code", "name", "start_date", "end_date", "ann_date", "change_reason",
    ),
    "stk_suspend": ("ts_code", "trade_date", "suspend_timing", "suspend_type"),
}

_CANONICAL_COLUMNS: dict[str, tuple[str, ...]] = {
    "instruments": (
        "symbol", "name", "asset", "market", "security_type", "source",
        "source_updated_at",
    ),
    "coverage": (
        "symbol", "frequency", "start_at", "end_at", "row_count", "source",
        "source_updated_at",
    ),
    "name_history": (
        "symbol", "name", "start_date", "end_date", "ann_date", "change_reason",
        "source",
    ),
    "suspensions": (
        "symbol", "trade_date", "suspend_timing", "suspend_type", "source",
    ),
}


def _manifest_core(manifest: dict[str, Any]) -> dict[str, Any]:
    if manifest.get("tier") != "full":
        raise ValueError(f"findb manifest tier 非 full: {manifest.get('tier')!r}")
    for item in manifest.get("files", []):
        if item.get("module") == "core" and item.get("name") == _CORE_FILE:
            return item
    raise ValueError("findb full MANIFEST 未包含 core.duckdb.zst")


def _decompress_zstd(source: Path, target: Path) -> None:
    import zstandard

    temporary = target.with_suffix(target.suffix + ".part")
    try:
        with source.open("rb") as compressed, temporary.open("wb") as output:
            zstandard.ZstdDecompressor().copy_stream(compressed, output)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def _sql_path(path: Path) -> str:
    return str(path).replace("'", "''")


def _read_and_convert_core(
    path: Path,
    output: Path,
) -> tuple[dict[str, list[tuple]], dict[str, Any]]:
    """校验供应商 DuckDB，转换为自有 Parquet，并返回热层记录。"""
    import duckdb

    output.mkdir(parents=True, exist_ok=False)
    metadata = output / "metadata"
    factors = output / "adjust_factors"
    temporary = output / ".duckdb-temp"
    metadata.mkdir()
    temporary.mkdir()
    connection = duckdb.connect(str(path), read_only=True)
    try:
        connection.execute("SET memory_limit='1GB'")
        connection.execute("SET threads=2")
        connection.execute(f"SET temp_directory='{_sql_path(temporary)}'")
        existing = {
            row[0]
            for row in connection.execute(
                "SELECT table_name FROM duckdb_tables()"
            ).fetchall()
        }
        required = set(_HOT_TABLES) | {"adj_factor"}
        missing = required - existing
        if missing:
            raise ValueError(f"core.duckdb 缺表: {sorted(missing)}")

        hot: dict[str, list[tuple]] = {
            "instruments": connection.execute(
                """
                SELECT code AS symbol, name, asset, market,
                       type AS security_type, 'findb' AS source,
                       updated_at AS source_updated_at
                FROM symbols ORDER BY code
                """
            ).fetchall(),
            "coverage": connection.execute(
                """
                SELECT code AS symbol, freq AS frequency,
                       start_dt AS start_at, end_dt AS end_at,
                       rows AS row_count, 'findb' AS source,
                       updated_at AS source_updated_at
                FROM coverage ORDER BY code, freq
                """
            ).fetchall(),
            "name_history": connection.execute(
                """
                SELECT ts_code AS symbol, name, start_date, end_date,
                       ann_date, change_reason, 'findb' AS source
                FROM stk_namechange ORDER BY ts_code, start_date
                """
            ).fetchall(),
            "suspensions": connection.execute(
                """
                SELECT ts_code AS symbol, trade_date, suspend_timing,
                       suspend_type, 'findb' AS source
                FROM stk_suspend ORDER BY ts_code, trade_date
                """
            ).fetchall(),
        }
        counts: dict[str, int] = {}
        for table, columns in _HOT_TABLES.items():
            actual = {
                row[0]
                for row in connection.execute(f"DESCRIBE {table}").fetchall()
            }
            absent = set(columns) - actual
            if absent:
                raise ValueError(f"core.{table} 缺列: {sorted(absent)}")
            counts[table] = int(
                connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            )

        factor = connection.execute(
            """
            SELECT count(*), min(date), max(date), count(DISTINCT code)
            FROM adj_factor
            """
        ).fetchone()
        counts["adj_factor"] = int(factor[0])
        details: dict[str, Any] = {
            "counts": counts,
            "adj_factor_start": factor[1],
            "adj_factor_end": factor[2],
            "adj_factor_symbols": int(factor[3]),
        }

        exports = {
            "instruments": """
                SELECT code AS symbol, name, asset, market,
                       type AS security_type, 'findb' AS source,
                       updated_at AS source_updated_at
                FROM symbols ORDER BY symbol
            """,
            "coverage": """
                SELECT code AS symbol, freq AS frequency,
                       start_dt AS start_at, end_dt AS end_at,
                       rows AS row_count, 'findb' AS source,
                       updated_at AS source_updated_at
                FROM coverage ORDER BY symbol, frequency
            """,
            "name_history": """
                SELECT ts_code AS symbol, name, start_date, end_date,
                       ann_date, change_reason, 'findb' AS source
                FROM stk_namechange ORDER BY symbol, start_date
            """,
            "suspensions": """
                SELECT ts_code AS symbol, trade_date, suspend_timing,
                       suspend_type, 'findb' AS source
                FROM stk_suspend ORDER BY symbol, trade_date
            """,
        }
        for name, query in exports.items():
            target = _sql_path(metadata / f"{name}.parquet")
            connection.execute(
                f"COPY ({query}) TO '{target}' "
                "(FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 122880)"
            )

        factor_target = _sql_path(factors)
        connection.execute(
            f"""
            COPY (
                SELECT code AS symbol, date, qfq, hfq,
                       year(date)::SMALLINT AS year
                FROM adj_factor
                ORDER BY year, symbol, date
            ) TO '{factor_target}' (
                FORMAT PARQUET,
                COMPRESSION ZSTD,
                PARTITION_BY (year),
                ROW_GROUP_SIZE 122880
            )
            """
        )

        (output / "dataset.json").write_text(
            json.dumps(
                {
                    "schema_version": _POOL_SCHEMA_VERSION,
                    "source": "findb",
                    **details,
                },
                ensure_ascii=False,
                default=str,
                indent=2,
            )
        )
        return hot, details
    finally:
        connection.close()
        shutil.rmtree(temporary, ignore_errors=True)


def _read_data_pool(path: Path) -> tuple[dict[str, list[tuple]], dict[str, Any]]:
    """从已发布的自有 Parquet data pool 读取热层记录。"""
    import duckdb

    state = json.loads((path / "dataset.json").read_text())
    if state.get("schema_version") != _POOL_SCHEMA_VERSION:
        raise ValueError("data pool schema 版本不匹配，需要重新初始化")
    connection = duckdb.connect()
    try:
        hot = {
            name: connection.execute(
                "SELECT * FROM read_parquet(?)",
                [str(path / "metadata" / f"{name}.parquet")],
            ).fetchall()
            for name in _CANONICAL_COLUMNS
        }
    finally:
        connection.close()
    details = {
        "counts": state["counts"],
        "adj_factor_start": state["adj_factor_start"],
        "adj_factor_end": state["adj_factor_end"],
        "adj_factor_symbols": state["adj_factor_symbols"],
    }
    return hot, details


def _publish_current(root: Path, version: Path) -> None:
    """原子切换 current 软链接到新 data pool 版本。"""
    current = root / "pool" / "current"
    temporary = current.with_name(".current.tmp")
    temporary.unlink(missing_ok=True)
    temporary.symlink_to(version.name, target_is_directory=True)
    os.replace(temporary, current)


def _prune_core_versions(root: Path, keep: Path) -> None:
    pool = root / "pool"
    for candidate in pool.iterdir():
        if candidate.name in {"current", "modules"} or candidate == keep:
            continue
        if candidate.is_dir() and candidate.name.startswith("core-v"):
            shutil.rmtree(candidate)


async def _replace_hot_tables(hot: dict[str, list[tuple]]) -> None:
    pool = await get_pool()
    async with pool.acquire() as connection:
        async with connection.transaction():
            await connection.execute(
                """
                CREATE TEMP TABLE instrument_master_stage
                    (LIKE instrument_master INCLUDING DEFAULTS) ON COMMIT DROP;
                CREATE TEMP TABLE data_coverage_stage
                    (LIKE data_coverage INCLUDING DEFAULTS) ON COMMIT DROP;
                CREATE TEMP TABLE instrument_name_history_stage
                    (LIKE instrument_name_history INCLUDING DEFAULTS) ON COMMIT DROP;
                CREATE TEMP TABLE trading_suspensions_stage
                    (LIKE trading_suspensions INCLUDING DEFAULTS) ON COMMIT DROP;
                """
            )
            await connection.copy_records_to_table(
                "instrument_master_stage",
                records=hot["instruments"],
                columns=list(_CANONICAL_COLUMNS["instruments"]),
            )
            await connection.copy_records_to_table(
                "data_coverage_stage",
                records=hot["coverage"],
                columns=list(_CANONICAL_COLUMNS["coverage"]),
            )
            await connection.copy_records_to_table(
                "instrument_name_history_stage",
                records=hot["name_history"],
                columns=list(_CANONICAL_COLUMNS["name_history"]),
            )
            await connection.copy_records_to_table(
                "trading_suspensions_stage",
                records=hot["suspensions"],
                columns=list(_CANONICAL_COLUMNS["suspensions"]),
            )
            await connection.execute(
                """
                DELETE FROM instrument_master WHERE source = 'findb';
                DELETE FROM data_coverage WHERE source = 'findb';
                DELETE FROM instrument_name_history WHERE source = 'findb';
                DELETE FROM trading_suspensions WHERE source = 'findb';
                INSERT INTO instrument_master SELECT * FROM instrument_master_stage;
                INSERT INTO data_coverage SELECT * FROM data_coverage_stage;
                INSERT INTO instrument_name_history
                    SELECT * FROM instrument_name_history_stage;
                INSERT INTO trading_suspensions SELECT * FROM trading_suspensions_stage;
                """
            )


async def run_findb_metadata_full_job() -> int:
    """下载 findb core，转换为自有 data pool；仅允许人工触发。"""
    logger.info("=== findb metadata full job start ===")
    root = Path(settings.DATA_POOL_ROOT)
    versions = root / "pool"
    staging_root = root / "staging"
    versions.mkdir(parents=True, exist_ok=True)
    staging_root.mkdir(parents=True, exist_ok=True)

    manifest = await asyncio.to_thread(findb_archive_source.full_manifest)
    core = _manifest_core(manifest)
    expected_sha = str(core["sha256"])
    version_name = f"core-v{_POOL_SCHEMA_VERSION}-{expected_sha[:16]}"
    version = versions / version_name

    if version.exists():
        hot, details = await asyncio.to_thread(_read_data_pool, version)
    else:
        staging = staging_root / f"{version_name}-{os.getpid()}"
        shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir()
        compressed = staging / _CORE_FILE
        database = staging / "core.duckdb"
        converted = staging / "dataset"
        try:
            key = f"{settings.FINDB_ARCHIVE_PREFIX}/{_CORE_FILE}"
            size = await asyncio.to_thread(
                findb_archive_source.download, key, compressed, expected_sha
            )
            logger.info("findb core 下载完成: %d bytes", size)
            await asyncio.to_thread(_decompress_zstd, compressed, database)
            hot, details = await asyncio.to_thread(
                _read_and_convert_core, database, converted
            )
            # 发布的是 tradeck 自有 Parquet；供应商 zst/DuckDB 不进入持久层。
            os.replace(converted, version)
        except BaseException:
            # 未发布的残缺版本不可被下一次任务误判为可复用版本。
            shutil.rmtree(version, ignore_errors=True)
            raise
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    await _replace_hot_tables(hot)
    # PostgreSQL 热层成功后再切换当前冷层版本，避免 PG 导入失败时 current
    # 已提前指向新快照。
    await asyncio.to_thread(_publish_current, root, version)

    pool = await get_pool()
    async with pool.acquire() as connection:
        built_at = datetime.fromisoformat(str(manifest["built_at"]))
        await connection.execute(
            """
            INSERT INTO data_pool_state
                (module, source, tier, built_at, sha256, local_path, row_counts, synced_at)
            VALUES ('core_metadata', 'findb', $1, $2::timestamptz, $3, $4, $5::jsonb, NOW())
            ON CONFLICT (module) DO UPDATE SET
                source = EXCLUDED.source,
                tier = EXCLUDED.tier,
                built_at = EXCLUDED.built_at,
                sha256 = EXCLUDED.sha256,
                local_path = EXCLUDED.local_path,
                row_counts = EXCLUDED.row_counts,
                synced_at = NOW()
            """,
            manifest["tier"],
            built_at,
            expected_sha,
            str(version),
            json.dumps(details["counts"]),
        )
    await asyncio.to_thread(_prune_core_versions, root, version)

    imported = sum(len(rows) for rows in hot.values())
    logger.info(
        "=== findb metadata full job done: %d hot rows, %d adj factors in Parquet ===",
        imported,
        details["counts"]["adj_factor"],
    )
    return imported
