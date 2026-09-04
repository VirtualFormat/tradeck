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
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.config import settings
from app.datasource import findb_source
from app.db import get_pool
from app.quality import quality_gate

logger = logging.getLogger(__name__)

_BATCH_SIZE = 50
_ACTIVE_MAX_AGE_DAYS = 45
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

    zone = ZoneInfo({
        "CN": "Asia/Shanghai",
        "HK": "Asia/Hong_Kong",
        "US": "America/New_York",
    }[market])
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


def _delta_path(market: str, day: date) -> Path:
    return (
        Path(settings.DATA_POOL_ROOT)
        / "bars"
        / "minute_delta"
        / "asset=stock"
        / f"market={market}"
        / f"year={day.year}"
        / f"date={day.isoformat()}"
        / "part-000.parquet"
    )


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


def _compact_day(staging: Path, target: Path) -> int:
    import duckdb

    files = sorted(staging.glob("*.parquet"))
    if not files:
        return 0
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".parquet.part")
    connection = duckdb.connect()
    try:
        connection.execute("SET memory_limit='1GB'")
        connection.execute("SET threads=2")
        connection.execute(
            """
            COPY (
                SELECT * EXCLUDE(rank)
                FROM (
                    SELECT *, row_number() OVER (
                        PARTITION BY symbol,datetime ORDER BY source DESC
                    ) rank
                    FROM read_parquet(?,union_by_name=true)
                ) WHERE rank=1 ORDER BY symbol,datetime
            ) TO ? (FORMAT PARQUET,COMPRESSION ZSTD,ROW_GROUP_SIZE 122880)
            """,
            [[str(path) for path in files], str(temporary)],
        )
        count = int(
            connection.execute(
                "SELECT num_rows FROM parquet_file_metadata(?)", [str(temporary)]
            ).fetchone()[0]
        )
        os.replace(temporary, target)
        return count
    finally:
        connection.close()
        temporary.unlink(missing_ok=True)


async def _active_symbols(market: str) -> list[str]:
    suffixes = _MARKET_SUFFIX[market]
    pool = await get_pool()
    async with pool.acquire() as connection:
        rows = await connection.fetch(
            """
            WITH market_rows AS (
                SELECT symbol,end_at,
                       max(end_at) OVER () AS market_max
                FROM data_coverage
                WHERE source='findb' AND frequency='1min'
                  AND symbol LIKE ANY($1::text[])
            )
            SELECT symbol
            FROM market_rows
            WHERE end_at >= market_max - ($2 * INTERVAL '1 day')
            ORDER BY symbol
            """,
            [f"%{suffix}" for suffix in suffixes],
            _ACTIVE_MAX_AGE_DAYS,
        )
    return [row["symbol"] for row in rows]


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
    return [row["date"] for row in rows]


async def _sync_day(market: str, symbols: list[str], day: date) -> int:
    target = _delta_path(market, day)
    if target.exists():
        return 0
    staging = target.parent / f".staging-{os.getpid()}"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    successful_batches = 0
    try:
        for index, offset in enumerate(range(0, len(symbols), _BATCH_SIZE)):
            chunk = symbols[offset : offset + _BATCH_SIZE]
            raw = await findb_source.fetch_bars_batch(
                chunk,
                freq="1min",
                start=day.isoformat(),
                end=day.isoformat(),
                timeout=90.0,
                retries=2,
            )
            if not raw:
                continue
            accepted = await quality_gate(
                "minute_bars", _normalize_rows(raw, market), persist=False
            )
            if not accepted:
                continue
            await asyncio.to_thread(
                _write_batch, staging / f"batch-{index:04d}.parquet", accepted
            )
            successful_batches += 1

        expected_batches = (len(symbols) + _BATCH_SIZE - 1) // _BATCH_SIZE
        # 少量已退市/停牌标的会让个别批次无数据；低于 80% 视为源异常，不发布。
        if successful_batches < max(1, int(expected_batches * 0.8)):
            logger.warning(
                "minute_kline %s %s 批次不足: %d/%d，不发布",
                market,
                day,
                successful_batches,
                expected_batches,
            )
            return 0
        count = await asyncio.to_thread(_compact_day, staging, target)
        logger.info("minute_kline %s %s: %d rows", market, day, count)
        return count
    finally:
        shutil.rmtree(staging, ignore_errors=True)


async def run_minute_kline_job(day: date | None = None) -> dict[str, int]:
    """同步 full 基线末日后的所有已知交易日，已发布日期自动跳过。"""
    logger.info("=== minute kline job start ===")
    through = day or datetime.now(timezone.utc).date()
    counts: dict[str, int] = {}
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
            except Exception:  # noqa: BLE001
                logger.exception("minute_kline %s %s 增量失败", market, trade_day)
        counts[market] = total
    logger.info(
        "=== minute kline job done: %s ===",
        ", ".join(f"{market}={count}" for market, count in counts.items()),
    )
    return counts
