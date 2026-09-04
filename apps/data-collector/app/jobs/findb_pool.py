"""findb full 分发包 → tradeck 自有 data pool（仅手动执行）。

按模块串行处理，避免同时保留整档 127 GiB 压缩包：
- ``*.duckdb.zst``：逐表导出为 ZSTD Parquet；
- ``*.tar.zst[.partNN]``：合并分卷、流式解包，逐 Parquet 重写为规范列；
- 每个模块原子发布独立版本，成功后删除供应商原始包与 staging。

core 模块由 ``findb_metadata_full`` 专门处理（含热层 PG 镜像），本任务处理其余
模块。任务不注册 scheduler，只能通过运维 API 人工触发。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import tarfile
from collections import defaultdict
from pathlib import Path
from typing import Any

from app.config import settings
from app.datasource import findb_archive_source
from app.db import get_pool
from app.jobs.findb_metadata import run_findb_metadata_full_job
from app.jobs import progress

logger = logging.getLogger(__name__)

_SCHEMA_VERSION = 1


def _sql_literal(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _group_files(manifest: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in manifest.get("files", []):
        grouped[str(item["module"])].append(item)
    for items in grouped.values():
        items.sort(key=lambda item: item["name"])
    return dict(grouped)


async def _validate_manifest_objects(
    files: list[dict[str, Any]],
) -> None:
    """启动转换前比对对象长度；清单滞后只告警，不中断初始化。"""
    prefix = settings.FINDB_ARCHIVE_PREFIX
    for item in files:
        key = f"{prefix}/{item['name']}"
        metadata = await asyncio.to_thread(findb_archive_source.head, key)
        expected = int(item["bytes"])
        if metadata["bytes"] != expected:
            logger.warning(
                "findb MANIFEST 长度与 COS 对象不一致，继续使用实际对象："
                "%s manifest=%d bytes, cos=%d bytes, last_modified=%s",
                item["name"],
                expected,
                metadata["bytes"],
                metadata["last_modified"],
            )


def _module_digest(files: list[dict[str, Any]]) -> str:
    import hashlib

    digest = hashlib.sha256()
    for item in files:
        digest.update(str(item["name"]).encode())
        digest.update(str(item["sha256"]).encode())
    return digest.hexdigest()


def _decompress_zstd(source: Path, target: Path) -> None:
    import zstandard

    with source.open("rb") as compressed, target.open("wb") as output:
        zstandard.ZstdDecompressor().copy_stream(compressed, output)


def _safe_extract_tar_zstd(source: Path, target: Path) -> None:
    """流式解包，拒绝路径逃逸并忽略 macOS sidecar。"""
    import zstandard

    target_root = target.resolve()
    with source.open("rb") as compressed:
        with zstandard.ZstdDecompressor().stream_reader(compressed) as reader:
            with tarfile.open(fileobj=reader, mode="r|") as archive:
                for member in archive:
                    path = Path(member.name)
                    if any(part == ".." for part in path.parts):
                        raise ValueError(f"findb tar 含路径逃逸: {member.name!r}")
                    if path.name.startswith("._") or path.name == ".DS_Store":
                        continue
                    destination = (target / path).resolve()
                    destination.relative_to(target_root)
                    if member.isdir():
                        destination.mkdir(parents=True, exist_ok=True)
                        continue
                    if not member.isfile():
                        continue
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    fileobj = archive.extractfile(member)
                    if fileobj is None:
                        continue
                    with destination.open("wb") as output:
                        shutil.copyfileobj(fileobj, output, 4 * 1024 * 1024)


def _normalize_parquet(source: Path, target: Path, *, daily: bool) -> int:
    """重写供应商 Parquet：code→symbol、追加 source、ZSTD 压缩。"""
    import duckdb

    target.parent.mkdir(parents=True, exist_ok=True)
    temp_directory = target.parent / ".duckdb-temp"
    temp_directory.mkdir(exist_ok=True)
    connection = duckdb.connect()
    try:
        connection.execute("SET memory_limit='1GB'")
        connection.execute("SET threads=2")
        connection.execute(f"SET temp_directory={_sql_literal(temp_directory)}")
        columns = [
            row[0]
            for row in connection.execute(
                "DESCRIBE SELECT * FROM read_parquet(?)", [str(source)]
            ).fetchall()
        ]
        expressions = []
        for column in columns:
            if column == "code":
                expressions.append('"code" AS "symbol"')
            elif column == "datetime" and daily:
                expressions.append('CAST("datetime" AS DATE) AS "date"')
            else:
                expressions.append(f'"{column}"')
        if "source" not in columns:
            expressions.append("'findb'::VARCHAR AS source")

        order = []
        normalized = {
            "symbol" if column == "code"
            else "date" if column == "datetime" and daily
            else column
            for column in columns
        }
        if "symbol" in normalized:
            order.append("symbol")
        if "datetime" in normalized:
            order.append("datetime")
        elif "date" in normalized:
            order.append("date")
        order_sql = f" ORDER BY {', '.join(order)}" if order else ""
        temporary = target.with_suffix(target.suffix + ".part")
        query = (
            f"SELECT {', '.join(expressions)} FROM read_parquet("
            f"{_sql_literal(source)}, union_by_name=true){order_sql}"
        )
        connection.execute(
            f"COPY ({query}) TO {_sql_literal(temporary)} "
            "(FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 122880)"
        )
        rows = int(
            connection.execute(
                "SELECT num_rows FROM parquet_file_metadata(?)", [str(temporary)]
            ).fetchone()[0]
        )
        os.replace(temporary, target)
        return rows
    finally:
        connection.close()
        shutil.rmtree(temp_directory, ignore_errors=True)


def _convert_archive_module(
    extracted: Path,
    output: Path,
    module: str,
) -> tuple[int, int]:
    files = [
        path
        for path in extracted.rglob("*.parquet")
        if not path.name.startswith("._")
    ]
    rows = 0
    daily = module.endswith("_daily") or module == "macro_series"
    for source in sorted(files):
        relative = source.relative_to(extracted)
        rows += _normalize_parquet(source, output / relative, daily=daily)
    return len(files), rows


def _convert_duckdb_module(source: Path, output: Path) -> tuple[int, int]:
    import duckdb

    output.mkdir(parents=True, exist_ok=False)
    temp_directory = output / ".duckdb-temp"
    temp_directory.mkdir()
    connection = duckdb.connect(str(source), read_only=True)
    total = 0
    try:
        connection.execute("SET memory_limit='1GB'")
        connection.execute("SET threads=2")
        connection.execute(f"SET temp_directory={_sql_literal(temp_directory)}")
        tables = [
            row[0]
            for row in connection.execute(
                "SELECT table_name FROM duckdb_tables() ORDER BY table_name"
            ).fetchall()
        ]
        for table in tables:
            columns = [row[0] for row in connection.execute(f"DESCRIBE {table}").fetchall()]
            expressions = [
                f'"{column}" AS "{"symbol" if column in {"code", "ts_code"} else column}"'
                for column in columns
            ]
            if "source" not in columns:
                expressions.append("'findb'::VARCHAR AS source")
            target = output / f"{table}.parquet"
            query = f'SELECT {", ".join(expressions)} FROM "{table}"'
            connection.execute(
                f"COPY ({query}) TO {_sql_literal(target)} "
                "(FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 122880)"
            )
            total += int(connection.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0])
        return len(tables), total
    finally:
        connection.close()
        shutil.rmtree(temp_directory, ignore_errors=True)


def _publish(module_root: Path, version: Path) -> None:
    current = module_root / "current"
    temporary = module_root / ".current.tmp"
    temporary.unlink(missing_ok=True)
    temporary.symlink_to(version.name, target_is_directory=True)
    os.replace(temporary, current)


def _prune_versions(module_root: Path, keep: Path) -> None:
    """只保留当前模块版本；统一 bars 下的硬链接不会因此丢数据。"""
    for candidate in module_root.iterdir():
        if candidate.name == "current" or candidate == keep:
            continue
        if candidate.is_dir() and candidate.name.startswith("v"):
            shutil.rmtree(candidate)


_MARKET_MODULES = {
    "stock_daily": ("daily", "stock", "CN"),
    "future_daily": ("daily", "future", "CN"),
    "etf_daily": ("daily", "etf", "CN"),
    "index_daily": ("daily", "index", "GLOBAL"),
    "us_stock_daily": ("daily", "stock", "US"),
    "hk_stock_daily": ("daily", "stock", "HK"),
    "stock_1min": ("minute", "stock", "CN"),
    "future_1min": ("minute", "future", "CN"),
    "etf_1min": ("minute", "etf", "CN"),
    "index_1min": ("minute", "index", "GLOBAL"),
    "us_stock_1min": ("minute", "stock", "US"),
    "hk_stock_1min": ("minute", "stock", "HK"),
    "crypto_1min": ("minute", "crypto", "GLOBAL"),
}


def _replace_hardlink(source: Path, target: Path, *, overwrite: bool) -> None:
    if target.exists() and not overwrite:
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".link")
    temporary.unlink(missing_ok=True)
    os.link(source, temporary)
    os.replace(temporary, target)


def _materialize_market_module(
    root: Path,
    module: str,
    version: Path,
    *,
    overwrite: bool,
) -> None:
    """把版本快照零拷贝发布到统一 bars 目录（同文件系统硬链接）。"""
    if module == "macro_series":
        mapping = {
            "forex_daily": ("daily", "forex", "GLOBAL"),
            "commodity_daily": ("daily", "commodity", "GLOBAL"),
            "crypto_daily": ("daily", "crypto", "GLOBAL"),
        }
        package_root = version / module
        if not package_root.exists():
            package_root = version
        for category, layout in mapping.items():
            base = package_root / category
            if not base.exists():
                continue
            frequency, asset, market = layout
            for source in base.rglob("*.parquet"):
                _replace_hardlink(
                    source,
                    root / "bars" / frequency / f"asset={asset}"
                    / f"market={market}" / source.relative_to(base),
                    overwrite=overwrite,
                )
        return

    layout = _MARKET_MODULES.get(module)
    if layout is None:
        return
    frequency, asset, market = layout
    source_root = version / module
    if not source_root.exists():
        # 防未来供应商移除 tar 内顶层目录。
        source_root = version
    for source in source_root.rglob("*.parquet"):
        relative = source.relative_to(source_root)
        # 1min 包当前是 {symbol}/{year}.parquet，规范为 symbol=<code>/year=<year>。
        if frequency == "minute" and len(relative.parts) >= 2:
            symbol = relative.parts[0]
            filename = relative.name
            if not filename.startswith("year="):
                filename = f"year={Path(filename).stem}.parquet"
            relative = Path(f"symbol={symbol}") / filename
        _replace_hardlink(
            source,
            root / "bars" / frequency / f"asset={asset}"
            / f"market={market}" / relative,
            overwrite=overwrite,
        )


async def _record_state(
    module: str,
    manifest: dict[str, Any],
    digest: str,
    version: Path,
    files: int,
    rows: int,
) -> None:
    from datetime import datetime

    pool = await get_pool()
    async with pool.acquire() as connection:
        await connection.execute(
            """
            INSERT INTO data_pool_state
                (module, source, tier, built_at, sha256, local_path, row_counts, synced_at)
            VALUES ($1, 'findb', $2, $3, $4, $5, $6::jsonb, NOW())
            ON CONFLICT (module) DO UPDATE SET
                source=EXCLUDED.source, tier=EXCLUDED.tier,
                built_at=EXCLUDED.built_at, sha256=EXCLUDED.sha256,
                local_path=EXCLUDED.local_path, row_counts=EXCLUDED.row_counts,
                synced_at=NOW()
            """,
            module,
            manifest["tier"],
            datetime.fromisoformat(str(manifest["built_at"])),
            digest,
            str(version),
            json.dumps({"files": files, "rows": rows}),
        )


async def _import_module(
    module: str,
    files: list[dict[str, Any]],
    manifest: dict[str, Any],
) -> int:
    root = Path(settings.DATA_POOL_ROOT)
    module_root = root / "pool" / "modules" / module
    module_root.mkdir(parents=True, exist_ok=True)
    digest = _module_digest(files)
    version = module_root / f"v{_SCHEMA_VERSION}-{digest[:16]}"
    if version.exists():
        state = json.loads((version / "dataset.json").read_text())
        _publish(module_root, version)
        # 同一供应商版本重跑只补缺失链接，不能覆盖已经写入的每日增量。
        _materialize_market_module(root, module, version, overwrite=False)
        await _record_state(
            module, manifest, digest, version, state["files"], state["rows"]
        )
        _prune_versions(module_root, version)
        return int(state["rows"])

    staging = root / "staging" / f"{module}-{os.getpid()}"
    shutil.rmtree(staging, ignore_errors=True)
    downloads = staging / "downloads"
    extracted = staging / "extracted"
    converted = staging / "converted"
    downloads.mkdir(parents=True)
    try:
        for item in files:
            key = f"{settings.FINDB_ARCHIVE_PREFIX}/{item['name']}"
            await asyncio.to_thread(
                findb_archive_source.download,
                key,
                downloads / item["name"],
                str(item["sha256"]),
            )

        names = [str(item["name"]) for item in files]
        if len(files) == 1 and names[0].endswith(".duckdb.zst"):
            database = staging / f"{module}.duckdb"
            await asyncio.to_thread(
                _decompress_zstd, downloads / names[0], database
            )
            file_count, row_count = await asyncio.to_thread(
                _convert_duckdb_module, database, converted
            )
        else:
            archive = staging / f"{module}.tar.zst"
            with archive.open("wb") as output:
                for name in names:
                    with (downloads / name).open("rb") as part:
                        shutil.copyfileobj(part, output, 4 * 1024 * 1024)
            extracted.mkdir()
            await asyncio.to_thread(_safe_extract_tar_zstd, archive, extracted)
            converted.mkdir()
            file_count, row_count = await asyncio.to_thread(
                _convert_archive_module, extracted, converted, module
            )

        (converted / "dataset.json").write_text(
            json.dumps(
                {
                    "schema_version": _SCHEMA_VERSION,
                    "source": "findb",
                    "module": module,
                    "source_built_at": manifest["built_at"],
                    "source_digest": digest,
                    "files": file_count,
                    "rows": row_count,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        os.replace(converted, version)
        _publish(module_root, version)
        # 供应商 full 快照是初始化基线；统一 bars 可能已包含更新的每日增量，
        # 因此这里只填缺失文件，不用较旧快照覆盖自有池。
        _materialize_market_module(root, module, version, overwrite=False)
        await _record_state(
            module, manifest, digest, version, file_count, row_count
        )
        _prune_versions(module_root, version)
        return row_count
    except BaseException:
        # 未完整发布的版本必须删除，断点重跑时从该模块重新转换。
        shutil.rmtree(version, ignore_errors=True)
        raise
    finally:
        shutil.rmtree(staging, ignore_errors=True)


async def run_findb_pool_full_job() -> dict[str, int]:
    """一次性导入 full 档全部模块；逐模块发布，可断点重跑。"""
    logger.info("=== findb data pool full job start ===")
    manifest = await asyncio.to_thread(findb_archive_source.full_manifest)
    if manifest.get("tier") != "full":
        raise ValueError("findb COS manifest 不是 full 档")
    grouped = _group_files(manifest)
    progress.job_set_total("findb_pool_full", len(grouped))
    await _validate_manifest_objects(
        [item for files in grouped.values() for item in files]
    )
    result: dict[str, int] = {
        "core": await run_findb_metadata_full_job(),
    }
    processed = 1
    progress.job_update("findb_pool_full", processed)
    modules = [module for module in grouped if module != "core"]
    # 先日线/小型 DuckDB，最后处理百 GB 级分钟线；断点重跑时已发布模块直接复用。
    modules.sort(key=lambda module: ("1min" in module, module))
    for module in modules:
        files = grouped[module]
        logger.info("findb data pool 导入模块 %s（%d 文件）", module, len(files))
        result[module] = await _import_module(module, files, manifest)
        processed += 1
        progress.job_update("findb_pool_full", processed)
        logger.info("findb data pool 模块 %s 完成：%d 行", module, result[module])
    logger.info("=== findb data pool full job done: %s ===", result)
    return result
