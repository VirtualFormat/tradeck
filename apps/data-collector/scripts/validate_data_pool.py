#!/usr/bin/env python3
"""只读校验 tradeck 自有 data pool，并输出机器可读 JSON 报告。

校验分为三层：
1. findb 模块清单与实际 Parquet footer 行数、文件可读性；
2. 股票日 K / 分钟 K 的物理覆盖范围与分区一致性；
3. PostgreSQL 元数据截止日之后，每个市场应有的分钟增量分区是否齐全。

脚本不读取完整分钟 K 数据，只扫描 Parquet footer；日 K 体量较小，会用 DuckDB
逐行聚合日期与标的覆盖。整个过程不会修改数据库或 data pool。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import statistics
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

MARKET_SUFFIXES = {
    "CN": (".SH", ".SZ", ".BJ"),
    "HK": (".HK",),
    "US": (".US",),
}
STOCK_MINUTE_MODULES = {
    "CN": "stock_1min",
    "HK": "hk_stock_1min",
    "US": "us_stock_1min",
}
YEAR_RE = re.compile(r"(?:year=)?(19\d{2}|20\d{2})\.parquet$")


def _json_default(value: Any) -> str:
    if isinstance(value, (date, datetime, Path)):
        return value.isoformat() if not isinstance(value, Path) else str(value)
    raise TypeError(f"无法序列化 {type(value).__name__}")


def _scalar(value: Any) -> Any:
    if hasattr(value, "as_py"):
        value = value.as_py()
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return value


def _min_value(left: Any, right: Any) -> Any:
    if left is None:
        return right
    if right is None:
        return left
    return min(left, right)


def _max_value(left: Any, right: Any) -> Any:
    if left is None:
        return right
    if right is None:
        return left
    return max(left, right)


def _as_datetime(value: Any) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    return datetime.fromisoformat(str(value))


def _footer_summary(path: Path, time_columns: Iterable[str]) -> dict[str, Any]:
    import pyarrow.parquet as pq

    metadata = pq.read_metadata(path)
    names = metadata.schema.names
    selected = next((name for name in time_columns if name in names), None)
    minimum = None
    maximum = None
    nulls = 0
    if selected is not None:
        column_index = names.index(selected)
        for index in range(metadata.num_row_groups):
            statistics = metadata.row_group(index).column(column_index).statistics
            if statistics is None:
                continue
            if statistics.has_min_max:
                minimum = _min_value(minimum, _scalar(statistics.min))
                maximum = _max_value(maximum, _scalar(statistics.max))
            if statistics.null_count is not None:
                nulls += int(statistics.null_count)
    return {
        "rows": int(metadata.num_rows),
        "row_groups": int(metadata.num_row_groups),
        "time_column": selected,
        "min_time": minimum,
        "max_time": maximum,
        "time_nulls": nulls,
    }


def _scan_module(module_root: Path) -> dict[str, Any]:
    import pyarrow.parquet as pq

    current = module_root / "current"
    if not current.exists():
        return {"status": "missing_current"}
    version = current.resolve()
    dataset_path = version / "dataset.json"
    if not dataset_path.exists():
        return {"status": "missing_dataset_json", "version": str(version)}
    declared = json.loads(dataset_path.read_text())
    paths = sorted(version.rglob("*.parquet"))
    rows = 0
    failures = []
    empty_files = []
    minimum = None
    maximum = None
    temporal_files = 0
    for path in paths:
        try:
            footer = _footer_summary(
                path,
                (
                    "datetime",
                    "date",
                    "trade_date",
                    "cal_date",
                    "report_date",
                    "ann_date",
                    "end_date",
                    "start_date",
                ),
            )
            count = int(footer["rows"])
            rows += count
            if count == 0:
                empty_files.append(str(path.relative_to(version)))
            if footer["time_column"] and footer["min_time"] is not None:
                file_min = str(footer["min_time"])
                file_max = str(footer["max_time"])
                minimum = file_min if minimum is None else min(minimum, file_min)
                maximum = file_max if maximum is None else max(maximum, file_max)
                temporal_files += 1
        except Exception as exc:  # noqa: BLE001 - 校验器需收集全部坏文件
            failures.append({"file": str(path), "error": str(exc)[:500]})
    expected_files = int(declared.get("files", -1))
    expected_rows = int(declared.get("rows", -1))
    return {
        "status": "ok" if not failures else "corrupt",
        "version": str(version),
        "source_built_at": declared.get("source_built_at"),
        "declared_files": expected_files,
        "actual_files": len(paths),
        "file_count_matches": expected_files == len(paths),
        "declared_rows": expected_rows,
        "footer_rows": rows,
        "row_count_matches": expected_rows == rows,
        "temporal_files": temporal_files,
        "min_time": minimum,
        "max_time": maximum,
        "empty_files": empty_files[:100],
        "empty_file_count": len(empty_files),
        "failures": failures[:100],
        "failure_count": len(failures),
    }


def scan_modules(root: Path) -> dict[str, Any]:
    import pyarrow.parquet as pq

    modules_root = root / "pool" / "modules"
    result = {}
    if not modules_root.exists():
        return result
    for module_root in sorted(path for path in modules_root.iterdir() if path.is_dir()):
        print(f"[modules] {module_root.name}", file=sys.stderr, flush=True)
        result[module_root.name] = _scan_module(module_root)
    core_link = root / "pool" / "current"
    core_root = core_link.resolve() if core_link.exists() else None
    if core_root is not None and (core_root / "dataset.json").exists():
        print("[modules] core_metadata", file=sys.stderr, flush=True)
        declared = json.loads((core_root / "dataset.json").read_text())
        paths = sorted(core_root.rglob("*.parquet"))
        failures = []
        rows = 0
        for path in paths:
            try:
                rows += int(pq.read_metadata(path).num_rows)
            except Exception as exc:  # noqa: BLE001
                failures.append({"file": str(path), "error": str(exc)[:500]})
        result["core_metadata"] = {
            "status": "ok" if not failures else "corrupt",
            "version": str(core_root),
            "source_built_at": declared.get("source_built_at"),
            "actual_files": len(paths),
            "footer_rows": rows,
            "declared_row_counts": declared.get("row_counts", {}),
            "failure_count": len(failures),
            "failures": failures,
        }
    return result


def _partition_year(path: Path) -> int | None:
    match = YEAR_RE.search(path.name)
    return int(match.group(1)) if match else None


def scan_stock_minute(root: Path) -> dict[str, Any]:
    result: dict[str, Any] = {}
    base = root / "bars" / "minute" / "asset=stock"
    for market in ("CN", "HK", "US"):
        market_root = base / f"market={market}"
        files = sorted(market_root.glob("symbol=*/*.parquet"))
        total_rows = 0
        minimum = None
        maximum = None
        corrupt = []
        empty = []
        year_mismatches = []
        symbol_ranges: dict[str, dict[str, Any]] = {}
        for index, path in enumerate(files, 1):
            if index == 1 or index % 5000 == 0:
                print(
                    f"[minute] {market} {index}/{len(files)}",
                    file=sys.stderr,
                    flush=True,
                )
            try:
                footer = _footer_summary(path, ("datetime", "ts", "date"))
            except Exception as exc:  # noqa: BLE001
                corrupt.append({"file": str(path), "error": str(exc)[:500]})
                continue
            rows = int(footer["rows"])
            total_rows += rows
            if rows == 0:
                empty.append(str(path))
            file_min = footer["min_time"]
            file_max = footer["max_time"]
            minimum = _min_value(minimum, file_min)
            maximum = _max_value(maximum, file_max)
            year = _partition_year(path)
            years = {
                value.year
                for value in (file_min, file_max)
                if isinstance(value, (date, datetime))
            }
            if year is not None and years and years != {year}:
                year_mismatches.append(
                    {
                        "file": str(path),
                        "partition_year": year,
                        "min_time": file_min,
                        "max_time": file_max,
                    }
                )
            symbol = path.parent.name.removeprefix("symbol=")
            state = symbol_ranges.setdefault(
                symbol, {"rows": 0, "min_time": None, "max_time": None, "years": []}
            )
            state["rows"] += rows
            state["min_time"] = _min_value(state["min_time"], file_min)
            state["max_time"] = _max_value(state["max_time"], file_max)
            if year is not None:
                state["years"].append(year)

        missing_year_partitions = []
        end_dates = Counter()
        for symbol, state in symbol_ranges.items():
            years = sorted(set(state.pop("years")))
            if years:
                absent = sorted(set(range(years[0], years[-1] + 1)) - set(years))
                if absent:
                    missing_year_partitions.append({"symbol": symbol, "years": absent})
            end = state["max_time"]
            if isinstance(end, datetime):
                end_dates[end.date().isoformat()] += 1
            elif isinstance(end, date):
                end_dates[end.isoformat()] += 1
        result[market] = {
            "files": len(files),
            "symbols": len(symbol_ranges),
            "rows": total_rows,
            "min_time": minimum,
            "max_time": maximum,
            "corrupt_file_count": len(corrupt),
            "corrupt_files": corrupt[:100],
            "empty_file_count": len(empty),
            "empty_files": empty[:100],
            "year_mismatch_count": len(year_mismatches),
            "year_mismatches": year_mismatches[:100],
            "missing_year_partition_count": len(missing_year_partitions),
            "missing_year_partitions": missing_year_partitions[:100],
            "top_end_dates": end_dates.most_common(20),
            "symbol_ranges": symbol_ranges,
        }
    return result


def _daily_files(root: Path, market: str) -> list[Path]:
    market_root = root / "bars" / "daily" / "asset=stock" / f"market={market}"
    return sorted(market_root.glob("*.parquet"))


def _sql_path_list(paths: list[Path]) -> str:
    values = ["'" + str(path).replace("'", "''") + "'" for path in paths]
    return "[" + ",".join(values) + "]"


def scan_stock_daily(root: Path) -> dict[str, Any]:
    import duckdb

    connection = duckdb.connect()
    temp = root / "staging" / "validation-duckdb"
    temp.mkdir(parents=True, exist_ok=True)
    connection.execute("SET memory_limit='1GB'")
    connection.execute("SET threads=2")
    connection.execute("SET temp_directory=?", [str(temp)])
    result: dict[str, Any] = {}
    try:
        for market in ("CN", "HK", "US"):
            paths = _daily_files(root, market)
            print(f"[daily] {market} {len(paths)} files", file=sys.stderr, flush=True)
            failures = []
            good_paths = []
            footer_rows = 0
            layouts = Counter()
            for path in paths:
                layouts[
                    "year_equals" if path.name.startswith("year=") else "plain_year"
                ] += 1
                try:
                    footer_rows += int(pq.read_metadata(path).num_rows)
                    good_paths.append(str(path))
                except Exception as exc:  # noqa: BLE001
                    failures.append({"file": str(path), "error": str(exc)[:500]})
            if not good_paths:
                result[market] = {"files": 0, "failures": failures}
                continue
            path_sql = _sql_path_list([Path(path) for path in good_paths])
            query = """
                WITH source_rows AS (
                    SELECT symbol, CAST(date AS DATE) AS date, source
                    FROM read_parquet(__PATHS__, union_by_name=true, hive_partitioning=false)
                ), raw AS (
                    SELECT *, count(*) OVER (
                        PARTITION BY symbol,date
                    ) AS copy_count, row_number() OVER (
                        PARTITION BY symbol,date
                        ORDER BY CASE source
                            WHEN 'hithink' THEN 3
                            WHEN 'openbb' THEN 2
                            ELSE 1
                        END DESC
                    ) AS source_rank
                    FROM source_rows
                ), per_day AS (
                    SELECT date, count(*) AS row_count,
                           count(DISTINCT symbol) AS symbol_count,
                           sum(copy_count - 1) duplicate_rows
                    FROM raw WHERE source_rank=1 GROUP BY date
                )
                SELECT min(date), max(date), sum(row_count),
                       count(DISTINCT date), max(symbol_count), sum(duplicate_rows)
                FROM per_day
            """.replace("__PATHS__", path_sql)
            summary = connection.execute(query).fetchone()
            recent = connection.execute(f"""
                WITH source_rows AS (
                    SELECT symbol, CAST(date AS DATE) AS date, source
                    FROM read_parquet(
                        {path_sql}, union_by_name=true, hive_partitioning=false
                    )
                ), raw AS (
                    SELECT *, count(*) OVER (
                        PARTITION BY symbol,date
                    ) AS copy_count, row_number() OVER (
                        PARTITION BY symbol,date
                        ORDER BY CASE source
                            WHEN 'hithink' THEN 3
                            WHEN 'openbb' THEN 2
                            ELSE 1
                        END DESC
                    ) AS source_rank
                    FROM source_rows
                )
                SELECT date AS trade_date, count(*) AS row_count,
                       count(DISTINCT symbol) AS symbol_count,
                       sum(copy_count - 1) duplicate_rows,
                       string_agg(DISTINCT coalesce(source, 'NULL'), ',' ORDER BY coalesce(source, 'NULL')) sources
                FROM raw
                WHERE source_rank=1 AND date >= DATE '2026-08-15'
                GROUP BY date ORDER BY date
                """).fetchall()
            result[market] = {
                "files": len(paths),
                "layouts": dict(layouts),
                "footer_rows": footer_rows,
                "min_date": summary[0],
                "max_date": summary[1],
                "rows": int(summary[2] or 0),
                "trade_days": int(summary[3] or 0),
                "peak_symbols_per_day": int(summary[4] or 0),
                "duplicate_symbol_date_rows_after_overlay": int(summary[5] or 0),
                "recent_daily_coverage": [
                    {
                        "date": row[0],
                        "rows": int(row[1]),
                        "symbols": int(row[2]),
                        "duplicate_rows": int(row[3]),
                        "sources": row[4],
                    }
                    for row in recent
                ],
                "failure_count": len(failures),
                "failures": failures,
            }
    finally:
        connection.close()
        try:
            temp.rmdir()
        except OSError:
            pass
    return result


def _even_sample(values: list[str], size: int) -> list[str]:
    if len(values) <= size:
        return values
    if size <= 1:
        return [values[0]]
    indexes = {round(index * (len(values) - 1) / (size - 1)) for index in range(size)}
    return [values[index] for index in sorted(indexes)]


def scan_minute_daily_samples(
    root: Path,
    minute: dict[str, Any],
    sample_size: int,
) -> dict[str, Any]:
    """抽样比较分钟交易日与同标的日 K，识别分区内部的日期断层。"""
    import duckdb

    anchors = {
        "CN": ["000001.SZ", "300750.SZ", "600519.SH"],
        "HK": ["00700.HK", "00941.HK"],
        "US": ["AAPL.US", "MSFT.US", "NVDA.US", "SPY.US"],
    }
    connection = duckdb.connect()
    connection.execute("SET memory_limit='1GB'")
    connection.execute("SET threads=2")
    result: dict[str, Any] = {}
    try:
        for market in ("CN", "HK", "US"):
            ranges = minute.get(market, {}).get("symbol_ranges", {})
            if not ranges:
                result[market] = {"status": "no_minute_baseline"}
                continue
            latest = max(
                _as_datetime(state["max_time"])
                for state in ranges.values()
                if state["max_time"] is not None
            )
            latest_date = latest.date()
            candidates = sorted(
                symbol
                for symbol, state in ranges.items()
                if state["max_time"] is not None
                and (_as_datetime(state["max_time"]).date())
                >= latest_date - timedelta(days=7)
            )
            selected = _even_sample(candidates, sample_size)
            selected = sorted(
                set(selected + [s for s in anchors[market] if s in ranges])
            )
            minute_paths = [
                path
                for symbol in selected
                for path in sorted(
                    (
                        root
                        / "bars"
                        / "minute"
                        / "asset=stock"
                        / f"market={market}"
                        / f"symbol={symbol}"
                    ).glob("*.parquet")
                )
            ]
            daily_paths = _daily_files(root, market)
            print(
                f"[sample] {market} {len(selected)} symbols",
                file=sys.stderr,
                flush=True,
            )
            minute_rows = connection.execute(f"""
                SELECT symbol, CAST(datetime AS DATE) AS date,
                       count(*) AS bars,
                       count(*) - count(DISTINCT datetime) AS duplicate_bars
                FROM read_parquet(
                    {_sql_path_list(minute_paths)},
                    union_by_name=true, hive_partitioning=false
                )
                GROUP BY symbol,date ORDER BY symbol,date
                """).fetchall()
            # findb 自有池保留 .US 后缀；PG daily_prices 才使用裸美股代码。
            daily_symbols = selected
            symbol_sql = (
                "["
                + ",".join(
                    "'" + symbol.replace("'", "''") + "'" for symbol in daily_symbols
                )
                + "]"
            )
            daily_rows = connection.execute(f"""
                SELECT DISTINCT symbol, CAST(date AS DATE) AS date
                FROM read_parquet(
                    {_sql_path_list(daily_paths)},
                    union_by_name=true, hive_partitioning=false
                )
                WHERE symbol IN {symbol_sql}
                ORDER BY symbol,date
                """).fetchall()

            actual: dict[str, dict[date, tuple[int, int]]] = defaultdict(dict)
            for symbol, day, bars, duplicates in minute_rows:
                actual[symbol][day] = (int(bars), int(duplicates))
            expected: dict[str, set[date]] = defaultdict(set)
            for symbol, day in daily_rows:
                expected[symbol].add(day)

            missing = []
            low_bar_days = []
            duplicate_bar_days = []
            expected_count = 0
            actual_count = 0
            for symbol in selected:
                state = ranges[symbol]
                start_date = _as_datetime(state["min_time"]).date()
                end_date = _as_datetime(state["max_time"]).date()
                expected_days = sorted(
                    day
                    for day in expected.get(symbol, set())
                    if start_date <= day <= end_date
                )
                expected_count += len(expected_days)
                actual_days = actual.get(symbol, {})
                actual_count += len(actual_days)
                for day in expected_days:
                    if day not in actual_days:
                        missing.append({"symbol": symbol, "date": day})
                counts = [bars for bars, _ in actual_days.values() if bars > 0]
                median = statistics.median(counts) if counts else 0
                for day, (bars, duplicates) in actual_days.items():
                    if duplicates:
                        duplicate_bar_days.append(
                            {"symbol": symbol, "date": day, "duplicates": duplicates}
                        )
                    if (
                        median
                        and bars < median * 0.8
                        and day in expected.get(symbol, set())
                    ):
                        low_bar_days.append(
                            {
                                "symbol": symbol,
                                "date": day,
                                "bars": bars,
                                "symbol_median_bars": median,
                            }
                        )
            result[market] = {
                "sample_symbols": selected,
                "sample_symbol_count": len(selected),
                "expected_daily_backed_symbol_days": expected_count,
                "minute_symbol_days": actual_count,
                "missing_daily_backed_day_count": len(missing),
                "missing_daily_backed_days": missing[:200],
                "low_bar_day_count": len(low_bar_days),
                "low_bar_days": low_bar_days[:200],
                "duplicate_bar_day_count": len(duplicate_bar_days),
                "duplicate_bar_days": duplicate_bar_days[:200],
            }
    finally:
        connection.close()
    return result


def _increment_paths(root: Path, market: str, day: date) -> list[tuple[str, Path]]:
    return [
        (
            "full_market_overlay",
            root
            / "bars"
            / "minute_delta"
            / "asset=stock"
            / f"market={market}"
            / f"year={day.year}"
            / f"date={day.isoformat()}"
            / "part-000.parquet",
        ),
        (
            "legacy_tracked",
            root
            / "minute_bars"
            / f"year={day.year}"
            / f"market={market}"
            / f"date={day.isoformat()}"
            / "part-000.parquet",
        ),
    ]


def _increment_file_summary(path: Path) -> tuple[dict[str, Any], set[str]]:
    import pyarrow.parquet as pq

    summary = _footer_summary(path, ("datetime", "ts", "date"))
    table = pq.read_table(path, columns=["symbol"])
    symbols = {str(item) for item in table.column("symbol").to_pylist() if item}
    summary["symbols"] = len(symbols)
    return summary, symbols


async def _database_report(
    database_url: str,
    root: Path,
    minute: dict[str, Any],
) -> dict[str, Any]:
    import asyncpg

    connection = await asyncpg.connect(database_url)
    try:
        states = await connection.fetch("""
            SELECT module,source,tier,built_at,synced_at,row_counts,local_path
            FROM data_pool_state ORDER BY module
            """)
        daily = await connection.fetch("""
            SELECT market,date,count(*) rows,count(DISTINCT symbol) symbols
            FROM daily_prices WHERE date >= DATE '2026-08-15'
            GROUP BY market,date ORDER BY market,date
            """)
        report: dict[str, Any] = {
            "data_pool_state": [dict(row) for row in states],
            "recent_daily_prices": [dict(row) for row in daily],
            "minute_increment": {},
        }
        for market, suffixes in MARKET_SUFFIXES.items():
            physical_symbols = sorted(minute.get(market, {}).get("symbol_ranges", {}))
            if not physical_symbols:
                report["minute_increment"][market] = {"status": "no_baseline"}
                continue
            rows = await connection.fetch(
                """
                SELECT symbol,start_at,end_at,row_count
                FROM data_coverage
                WHERE source='findb' AND frequency='1min'
                  AND symbol=ANY($1::text[])
                ORDER BY symbol
                """,
                physical_symbols,
            )
            coverage = [dict(row) for row in rows]
            cutoff = max(
                (row["end_at"].date() for row in coverage if row["end_at"] is not None),
                default=None,
            )
            expected_days = []
            if cutoff is not None:
                expected_days = [
                    row["date"]
                    for row in await connection.fetch(
                        """
                        SELECT DISTINCT date FROM daily_prices
                        WHERE market=$1 AND date>$2 AND date<=CURRENT_DATE
                        ORDER BY date
                        """,
                        market,
                        cutoff,
                    )
                ]
            delta = []
            active_symbols = {
                row["symbol"]
                for row in coverage
                if row["end_at"] is not None
                and cutoff is not None
                and row["end_at"].date() >= cutoff - timedelta(days=45)
            }
            for day in expected_days:
                item: dict[str, Any] = {"date": day, "files": []}
                day_symbols: set[str] = set()
                for layout, path in _increment_paths(root, market, day):
                    if not path.exists():
                        continue
                    file_item: dict[str, Any] = {
                        "layout": layout,
                        "path": str(path),
                    }
                    try:
                        summary, symbols = _increment_file_summary(path)
                        file_item.update(summary)
                        day_symbols.update(symbols)
                    except Exception as exc:  # noqa: BLE001
                        file_item["error"] = str(exc)[:500]
                    item["files"].append(file_item)
                item["exists"] = bool(item["files"])
                item["rows"] = sum(file.get("rows", 0) for file in item["files"])
                item["symbols"] = len(day_symbols)
                item["active_symbol_coverage"] = (
                    round(len(day_symbols & active_symbols) / len(active_symbols), 6)
                    if active_symbols
                    else None
                )
                delta.append(item)

            end_dates = Counter(
                row["end_at"].date().isoformat()
                for row in coverage
                if row["end_at"] is not None
            )
            at_cutoff = end_dates.get(cutoff.isoformat(), 0) if cutoff else 0
            row_mismatches = []
            range_mismatches = []
            ranges = minute[market]["symbol_ranges"]
            for row in coverage:
                physical = ranges[row["symbol"]]
                if int(row["row_count"] or 0) != int(physical["rows"]):
                    row_mismatches.append(
                        {
                            "symbol": row["symbol"],
                            "metadata_rows": int(row["row_count"] or 0),
                            "physical_rows": int(physical["rows"]),
                        }
                    )
                physical_start = _as_datetime(physical["min_time"])
                physical_end = _as_datetime(physical["max_time"])
                if row["start_at"] != physical_start or row["end_at"] != physical_end:
                    range_mismatches.append(
                        {
                            "symbol": row["symbol"],
                            "metadata_start": row["start_at"],
                            "physical_start": physical_start,
                            "metadata_end": row["end_at"],
                            "physical_end": physical_end,
                        }
                    )
            report["minute_increment"][market] = {
                "physical_baseline_symbols": len(physical_symbols),
                "metadata_matched_symbols": len(coverage),
                "metadata_missing_symbols": sorted(
                    set(physical_symbols) - {row["symbol"] for row in coverage}
                )[:200],
                "baseline_cutoff": cutoff,
                "symbols_at_cutoff": at_cutoff,
                "symbols_behind_cutoff": len(coverage) - at_cutoff,
                "active_baseline_symbols": len(active_symbols),
                "metadata_row_mismatch_count": len(row_mismatches),
                "metadata_row_mismatches": row_mismatches[:100],
                "metadata_range_mismatch_count": len(range_mismatches),
                "metadata_range_mismatches": range_mismatches[:100],
                "top_baseline_end_dates": end_dates.most_common(20),
                "expected_increment_days": expected_days,
                "delta_partitions": delta,
                "missing_delta_days": [
                    item["date"] for item in delta if not item["exists"]
                ],
                "partial_delta_days": [
                    item["date"]
                    for item in delta
                    if item["exists"]
                    and item["active_symbol_coverage"] is not None
                    and item["active_symbol_coverage"] < 0.8
                ],
            }
        return report
    finally:
        await connection.close()


def _strip_symbol_ranges(report: dict[str, Any]) -> None:
    for market in report.get("stock_minute", {}).values():
        market.pop("symbol_ranges", None)


def _derive_findings(report: dict[str, Any]) -> dict[str, Any]:
    modules = report.get("modules", {})
    minute = report.get("stock_minute", {})
    daily = report.get("stock_daily", {})
    increments = report.get("database", {}).get("minute_increment", {})
    module_failures = [
        name
        for name, value in modules.items()
        if value.get("status") != "ok"
        or (
            "file_count_matches" in value and not value.get("file_count_matches", False)
        )
        or ("row_count_matches" in value and not value.get("row_count_matches", False))
        or value.get("failure_count", 0)
    ]
    missing_delta = {
        market: value.get("missing_delta_days", [])
        for market, value in increments.items()
        if value.get("missing_delta_days")
    }
    partial_delta = {
        market: value.get("partial_delta_days", [])
        for market, value in increments.items()
        if value.get("partial_delta_days")
    }
    metadata_mismatches = {
        market: {
            "rows": value.get("metadata_row_mismatch_count", 0),
            "ranges": value.get("metadata_range_mismatch_count", 0),
        }
        for market, value in increments.items()
        if value.get("metadata_row_mismatch_count", 0)
        or value.get("metadata_range_mismatch_count", 0)
    }
    stale_daily = {
        market: value.get("max_date")
        for market, value in daily.items()
        if value.get("max_date")
        and date.fromisoformat(str(value["max_date"])[:10])
        < date.today() - timedelta(days=3)
    }
    minute_file_failures = {
        market: value.get("corrupt_file_count", 0)
        for market, value in minute.items()
        if value.get("corrupt_file_count", 0)
    }
    blockers = []
    warnings = []
    if module_failures:
        blockers.append(f"模块清单/footer 校验失败: {', '.join(module_failures)}")
    if minute_file_failures:
        blockers.append(f"分钟 K 存在损坏文件: {minute_file_failures}")
    if missing_delta:
        blockers.append("findb 截止日之后的分钟 K delta 分区缺失")
    if partial_delta:
        blockers.append("findb 截止日之后的分钟 K 增量仅覆盖部分活跃标的")
    if metadata_mismatches:
        blockers.append(
            f"分钟 K 物理文件与 data_coverage 不一致: {metadata_mismatches}"
        )
    if stale_daily:
        blockers.append(f"统一日 K 池未更新至今天: {stale_daily}")
    for market, value in minute.items():
        if value.get("missing_year_partition_count", 0):
            warnings.append(
                f"{market} 有 {value['missing_year_partition_count']} 个标的存在年份分区间隔，"
                "需结合上市/停牌历史判断"
            )
    return {
        "verdict": "FAIL" if blockers else "PASS_WITH_WARNINGS" if warnings else "PASS",
        "quant_ready": not blockers,
        "blockers": blockers,
        "warnings": warnings,
    }


def _merge_report_files(report: dict[str, Any], paths: list[str]) -> None:
    """合并分阶段运行结果，避免大池校验因后续步骤失败而全部重扫。"""
    for name in paths:
        payload = json.loads(Path(name).read_text())
        for key in ("modules", "stock_minute", "stock_daily", "minute_daily_samples"):
            if key in payload:
                report[key] = payload[key]
        if "database" in payload:
            report["database"] = payload["database"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        default=os.getenv("DATA_POOL_ROOT", "/data/market-pool"),
        help="data pool 根目录",
    )
    parser.add_argument(
        "--database-url",
        default=os.getenv("DATABASE_URL", ""),
        help="PostgreSQL URL；留空则跳过数据库与增量接缝校验",
    )
    parser.add_argument("--output", help="JSON 输出文件；默认输出到 stdout")
    parser.add_argument(
        "--skip-modules", action="store_true", help="跳过所有 findb 模块 footer 校验"
    )
    parser.add_argument(
        "--skip-minute", action="store_true", help="跳过股票分钟 K footer 校验"
    )
    parser.add_argument(
        "--skip-daily", action="store_true", help="跳过股票日 K 聚合校验"
    )
    parser.add_argument(
        "--skip-samples", action="store_true", help="跳过分钟 K 与日 K 跨源抽样"
    )
    parser.add_argument(
        "--keep-symbol-ranges",
        action="store_true",
        help="在 JSON 中保留体积较大的逐标的分钟覆盖详情",
    )
    parser.add_argument(
        "--sample-size", type=int, default=24, help="每市场抽样的活跃股票数量"
    )
    parser.add_argument(
        "--merge-report",
        action="append",
        default=[],
        help="合并既有 JSON 分阶段结果，可重复指定",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.root).resolve()
    started_at = datetime.now().astimezone()
    report: dict[str, Any] = {
        "schema_version": 1,
        "root": str(root),
        "started_at": started_at,
    }
    _merge_report_files(report, args.merge_report)
    if not root.exists():
        raise SystemExit(f"data pool 不存在: {root}")

    if not args.skip_modules and "modules" not in report:
        report["modules"] = scan_modules(root)
    if not args.skip_minute and "stock_minute" not in report:
        report["stock_minute"] = scan_stock_minute(root)
    if not args.skip_daily and "stock_daily" not in report:
        report["stock_daily"] = scan_stock_daily(root)
    if (
        not args.skip_samples
        and "stock_minute" in report
        and "minute_daily_samples" not in report
    ):
        report["minute_daily_samples"] = scan_minute_daily_samples(
            root, report["stock_minute"], max(1, args.sample_size)
        )
    if args.database_url:
        report["database"] = asyncio.run(
            _database_report(args.database_url, root, report.get("stock_minute", {}))
        )
    report["findings"] = _derive_findings(report)
    if not args.keep_symbol_ranges:
        _strip_symbol_ranges(report)
    report["finished_at"] = datetime.now().astimezone()

    payload = json.dumps(report, ensure_ascii=False, indent=2, default=_json_default)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload + "\n")
        print(output)
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
