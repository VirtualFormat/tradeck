"""全市场股票分钟 K 增量：findb 批量 API → 自有增量 Parquet。

findb full 包已经提供 symbol/year 历史基线。每日按 data_coverage 中仍活跃的
CN/HK/US 股票，使用官方 ``codes`` 批量协议（≤50 只/请求）拉每个交易日增量，
写成 market/date 分区。查询层把历史基线与 delta 分区 UNION 后按
``symbol + datetime`` 去重即可。

这种 overlay 布局避免每天重写约 1.6 万个历史 symbol/year 文件，也把约 330 次/
交易日的请求控制在 findb 60 次/分钟限制内。失败日不发布最终文件，下轮重试。
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from app.config import settings
from app.datasource import findb_source
from app.db import get_pool
from app.quality import quality_gate
from app.jobs.minute_storage import (
    delta_path,
    merge_minute_files,
    parquet_row_count,
    parquet_symbols,
    read_delta_marker,
    write_delta_marker,
)

logger = logging.getLogger(__name__)

_BATCH_SIZE = 50
_ACTIVE_MAX_AGE_DAYS = 45
_MIN_SYMBOL_COVERAGE = 1.0
_FETCH_ROUNDS = 2
_MARKET_SUFFIX = {
    "CN": (".SH", ".SZ", ".BJ"),
    "HK": (".HK",),
    "US": (".US",),
}


def _number(value: Any) -> float | None:
    try:
        result = float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
    return None if result is not None and result != result else result


def _normalize_rows(raw: list[dict[str, Any]], market: str) -> list[dict[str, Any]]:
    from zoneinfo import ZoneInfo

    zone = ZoneInfo(
        {
            "CN": "Asia/Shanghai",
            "HK": "Asia/Hong_Kong",
            "US": "America/New_York",
        }[market]
    )
    result = []
    for item in raw:
        try:
            local_time = datetime.fromisoformat(
                str(item.get("datetime") or "").replace("Z", "")
            ).replace(tzinfo=None)
        except ValueError:
            continue
        close = _number(item.get("close"))
        symbol = str(item.get("code") or "").strip().upper()
        if not symbol or close is None:
            continue
        result.append(
            {
                "symbol": symbol,
                "market": market,
                "datetime": local_time,
                # 质量闸继续使用 UTC epoch；落盘只保留 datetime。
                "ts": int(local_time.replace(tzinfo=zone).timestamp()),
                "open": _number(item.get("open")),
                "high": _number(item.get("high")),
                "low": _number(item.get("low")),
                "close": close,
                "volume": _number(item.get("volume")),
                "amount": _number(item.get("amount")),
            }
        )
    return result


def _write_batch(path: Path, rows: list[dict[str, Any]]) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    payload = [
        {
            "symbol": row["symbol"],
            "datetime": row["datetime"],
            "open": row["open"],
            "high": row["high"],
            "low": row["low"],
            "close": row["close"],
            "volume": row["volume"],
            "amount": row["amount"],
            "source": "findb",
        }
        for row in rows
    ]
    table = pa.Table.from_pylist(payload).sort_by(
        [("symbol", "ascending"), ("datetime", "ascending")]
    )
    pq.write_table(table, path, compression="zstd")


async def _active_symbols(market: str) -> list[str]:
    suffixes = _MARKET_SUFFIX[market]
    baseline_root = (
        Path(settings.DATA_POOL_ROOT)
        / "bars"
        / "minute"
        / "asset=stock"
        / f"market={market}"
    )
    baseline_symbols = sorted(
        path.name.removeprefix("symbol=")
        for path in baseline_root.glob("symbol=*")
        if path.is_dir()
    )
    if not baseline_symbols:
        logger.warning("minute_kline %s 无 full 股票基线，跳过增量", market)
        return []
    pool = await get_pool()
    async with pool.acquire() as connection:
        rows = await connection.fetch(
            """
            WITH market_rows AS (
                SELECT symbol,end_at,
                       max(end_at) OVER () AS market_max
                FROM data_coverage
                WHERE source='findb' AND frequency='1min'
                  AND symbol = ANY($3::text[])
                  AND symbol LIKE ANY($1::text[])
            )
            SELECT symbol
            FROM market_rows
            WHERE end_at >= market_max - ($2 * INTERVAL '1 day')
            ORDER BY symbol
            """,
            [f"%{suffix}" for suffix in suffixes],
            _ACTIVE_MAX_AGE_DAYS,
            baseline_symbols,
        )
    return [row["symbol"] for row in rows]


async def _expected_symbols_for_day(
    market: str, active_symbols: list[str], day: date
) -> list[str]:
    """以当日日 K 为交易事实，只要求当天确有日 K 的 baseline 标的。"""
    canonical_to_pool = {
        (symbol[:-3] if market == "US" and symbol.endswith(".US") else symbol): symbol
        for symbol in active_symbols
    }
    pool = await get_pool()
    async with pool.acquire() as connection:
        rows = await connection.fetch(
            """
            SELECT symbol FROM daily_prices
            WHERE market=$1 AND date=$2 AND symbol=ANY($3::text[])
            ORDER BY symbol
            """,
            market,
            day,
            list(canonical_to_pool),
        )
    return [canonical_to_pool[row["symbol"]] for row in rows]


async def _expected_days(market: str, through: date) -> list[date]:
    """以 daily_prices 为交易日历；从 full coverage 末日后开始补。"""
    suffixes = _MARKET_SUFFIX[market]
    pool = await get_pool()
    async with pool.acquire() as connection:
        baseline_end = await connection.fetchval(
            """
            SELECT max(end_at::date)
            FROM data_coverage
            WHERE source='findb' AND frequency='1min'
              AND symbol LIKE ANY($1::text[])
            """,
            [f"%{suffix}" for suffix in suffixes],
        )
        if baseline_end is None:
            return []
        rows = await connection.fetch(
            """
            SELECT DISTINCT date
            FROM daily_prices
            WHERE market=$1 AND date > $2 AND date <= $3
            ORDER BY date
            """,
            market,
            baseline_end,
            through,
        )
    days = {row["date"] for row in rows}
    delta_root = (
        Path(settings.DATA_POOL_ROOT)
        / "bars"
        / "minute_delta"
        / "asset=stock"
        / f"market={market}"
    )
    for path in delta_root.glob("year=*/date=*/part-000.parquet"):
        try:
            day = date.fromisoformat(path.parent.name.removeprefix("date="))
        except ValueError:
            continue
        marker = read_delta_marker(path)
        if day <= through and (not marker or marker.get("complete") is not True):
            days.add(day)
    return sorted(days)


async def _sync_day(market: str, symbols: list[str], day: date) -> int:
    target = delta_path(market, day)
    expected = await _expected_symbols_for_day(market, symbols, day)
    if not expected:
        logger.info("minute_kline %s %s 无预期交易标的，跳过", market, day)
        return 0
    marker = read_delta_marker(target) if target.exists() else None
    if marker and marker.get("complete") is True:
        return 0
    staging = target.parent / f".staging-{os.getpid()}"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    existing_symbols = (
        await asyncio.to_thread(parquet_symbols, target) if target.exists() else set()
    )
    missing = set(expected) - existing_symbols
    fetched_rows = 0
    try:
        for round_index in range(_FETCH_ROUNDS):
            if not missing:
                break
            round_symbols = sorted(missing)
            returned: set[str] = set()
            for index, offset in enumerate(range(0, len(round_symbols), _BATCH_SIZE)):
                chunk = round_symbols[offset : offset + _BATCH_SIZE]
                raw = await findb_source.fetch_bars_batch(
                    chunk,
                    freq="1min",
                    start=day.isoformat(),
                    end=day.isoformat(),
                    timeout=90.0,
                    retries=2,
                )
                accepted = await quality_gate(
                    "minute_bars", _normalize_rows(raw, market), persist=False
                )
                if not accepted:
                    continue
                returned.update(row["symbol"] for row in accepted)
                fetched_rows += len(accepted)
                await asyncio.to_thread(
                    _write_batch,
                    staging / f"round-{round_index}-batch-{index:04d}.parquet",
                    accepted,
                )
            missing -= returned

        new_files = sorted(staging.glob("*.parquet"))
        if new_files:
            sources = ([target] if target.exists() else []) + new_files
            await asyncio.to_thread(merge_minute_files, sources, target)
        final_symbols = (
            await asyncio.to_thread(parquet_symbols, target)
            if target.exists()
            else set()
        )
        covered = len(set(expected) & final_symbols)
        coverage = covered / len(expected)
        complete = coverage >= _MIN_SYMBOL_COVERAGE
        total_rows = (
            await asyncio.to_thread(parquet_row_count, target) if target.exists() else 0
        )
        write_delta_marker(
            target,
            {
                "schema_version": 1,
                "market": market,
                "date": day,
                "expected_symbols": len(expected),
                "covered_symbols": covered,
                "symbol_coverage": round(coverage, 6),
                "rows": total_rows,
                "complete": complete,
                "updated_at": datetime.now(timezone.utc),
            },
        )
        if not complete:
            logger.warning(
                "minute_kline %s %s 覆盖不足: %d/%d (%.2f%%)，保留 partial 下轮续补",
                market,
                day,
                covered,
                len(expected),
                coverage * 100,
            )
        else:
            logger.info(
                "minute_kline %s %s 完成: %d rows, %d/%d symbols",
                market,
                day,
                total_rows,
                covered,
                len(expected),
            )
        return fetched_rows
    finally:
        shutil.rmtree(staging, ignore_errors=True)


async def run_minute_kline_job(day: date | None = None) -> dict[str, int]:
    """同步 full 基线末日后的所有已知交易日，已发布日期自动跳过。"""
    logger.info("=== minute kline job start ===")
    through = day or datetime.now(timezone.utc).date()
    counts: dict[str, int] = {}
    incomplete_days = 0
    for market in ("CN", "HK", "US"):
        symbols = await _active_symbols(market)
        days = await _expected_days(market, through)
        logger.info(
            "minute_kline %s: %d active symbols, %d missing trade days",
            market,
            len(symbols),
            len(days),
        )
        total = 0
        for trade_day in days:
            try:
                total += await _sync_day(market, symbols, trade_day)
                marker = read_delta_marker(delta_path(market, trade_day))
                if not marker or marker.get("complete") is not True:
                    incomplete_days += 1
            except Exception:  # noqa: BLE001
                logger.exception("minute_kline %s %s 增量失败", market, trade_day)
        counts[market] = total
    if incomplete_days:
        counts["incomplete_days"] = -incomplete_days
    logger.info(
        "=== minute kline job done: %s ===",
        ", ".join(f"{market}={count}" for market, count in counts.items()),
    )
    return counts
