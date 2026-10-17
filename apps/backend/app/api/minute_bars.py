"""POST /api/bars/minute：统一读取 symbol/year 基线与 market/date 增量。"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator

from app.api._service_auth import ServiceIdentity, quant_access
from app.config import settings
from app.markets import pick_market

logger = logging.getLogger(__name__)
router = APIRouter()

Symbol = Annotated[str, Field(pattern=r"^[A-Z0-9.\-]{1,20}$")]


class MinuteBarsRequest(BaseModel):
    symbols: Annotated[list[Symbol], Field(min_length=1, max_length=50)]
    start_date: date
    end_date: date
    limit: int = Field(default=200000, ge=1, le=500000)

    @field_validator("end_date")
    @classmethod
    def _valid_window(cls, value: date, info):
        start = info.data.get("start_date")
        if start is not None and value < start:
            raise ValueError("end_date 不能早于 start_date")
        if start is not None and (value - start).days > 366:
            raise ValueError("分钟 K 单次查询窗口不能超过 366 天")
        return value


def _pool_symbol(symbol: str) -> str:
    symbol = symbol.strip().upper()
    if pick_market(symbol) == "US" and not symbol.endswith(".US"):
        return f"{symbol}.US"
    return symbol


def _api_symbol(symbol: str) -> str:
    return symbol[:-3] if symbol.endswith(".US") else symbol


def _sql_literal(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _dates(start: date, end: date):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def _query_paths(
    root: Path, symbols: list[str], start: date, end: date
) -> tuple[list[Path], list[Path]]:
    baseline = []
    delta = []
    years = range(start.year, end.year + 1)
    markets = {pick_market(_api_symbol(symbol)) for symbol in symbols}
    for symbol in symbols:
        market = pick_market(_api_symbol(symbol))
        for year in years:
            path = (
                root
                / "bars"
                / "minute"
                / "asset=stock"
                / f"market={market}"
                / f"symbol={symbol}"
                / f"year={year}.parquet"
            )
            if path.exists():
                baseline.append(path)
    for market in markets:
        for day in _dates(start, end):
            path = (
                root
                / "bars"
                / "minute_delta"
                / "asset=stock"
                / f"market={market}"
                / f"year={day.year}"
                / f"date={day.isoformat()}"
                / "part-000.parquet"
            )
            if path.exists():
                delta.append(path)
    return baseline, delta


def _read_minute_bars(
    symbols: list[str], start: date, end: date, limit: int
) -> tuple[list[tuple], bool]:
    import duckdb

    root = Path(settings.DATA_POOL_ROOT)
    for attempt in range(2):
        baseline, delta = _query_paths(root, symbols, start, end)
        selects = []
        if baseline:
            paths = "[" + ",".join(_sql_literal(path) for path in baseline) + "]"
            selects.append(
                "SELECT *, 0::INTEGER AS _pool_priority "
                f"FROM read_parquet({paths},union_by_name=true,hive_partitioning=false)"
            )
        if delta:
            paths = "[" + ",".join(_sql_literal(path) for path in delta) + "]"
            selects.append(
                "SELECT *, 1::INTEGER AS _pool_priority "
                f"FROM read_parquet({paths},union_by_name=true,hive_partitioning=false)"
            )
        if not selects:
            return [], False
        placeholders = ",".join("?" for _ in symbols)
        start_at = datetime.combine(start, time.min)
        end_at = datetime.combine(end + timedelta(days=1), time.min)
        connection = duckdb.connect()
        try:
            connection.execute("SET memory_limit='384MB'")
            connection.execute("SET threads=2")
            rows = connection.execute(
                f"""
                SELECT symbol,datetime,open,high,low,close,volume,amount,source
                FROM (
                    SELECT *, row_number() OVER (
                        PARTITION BY symbol,datetime ORDER BY _pool_priority DESC
                    ) AS _rank
                    FROM ({' UNION ALL '.join(selects)})
                    WHERE symbol IN ({placeholders})
                      AND datetime >= ? AND datetime < ?
                )
                WHERE _rank=1
                ORDER BY symbol,datetime
                LIMIT ?
                """,
                [*symbols, start_at, end_at, limit + 1],
            ).fetchall()
            return rows[:limit], len(rows) > limit
        except (duckdb.IOException, duckdb.InvalidInputException):
            if attempt:
                raise
            logger.info("分钟 K 文件在查询期间发生切换，重建文件列表后重试")
        finally:
            connection.close()
    return [], False


@router.post("/api/bars/minute")
async def post_minute_bars(
    req: MinuteBarsRequest,
    identity: ServiceIdentity = Depends(quant_access),
):
    pool_symbols = sorted({_pool_symbol(symbol) for symbol in req.symbols})
    try:
        rows, truncated = await asyncio.to_thread(
            _read_minute_bars,
            pool_symbols,
            req.start_date,
            req.end_date,
            req.limit,
        )
    except Exception:  # noqa: BLE001
        logger.exception(
            "/api/bars/minute 查询失败 consumer=%s symbols=%d %s~%s",
            identity.name,
            len(pool_symbols),
            req.start_date,
            req.end_date,
        )
        return {"bars": [], "count": 0, "truncated": False}
    bars = [
        {
            "symbol": _api_symbol(row[0]),
            "datetime": row[1].isoformat() if row[1] else None,
            "open": float(row[2]) if row[2] is not None else None,
            "high": float(row[3]) if row[3] is not None else None,
            "low": float(row[4]) if row[4] is not None else None,
            "close": float(row[5]) if row[5] is not None else None,
            "volume": float(row[6]) if row[6] is not None else None,
            "amount": float(row[7]) if row[7] is not None else None,
            "source": row[8],
        }
        for row in rows
    ]
    logger.info(
        "/api/bars/minute consumer=%s symbols=%d rows=%d",
        identity.name,
        len(pool_symbols),
        len(bars),
    )
    return {"bars": bars, "count": len(bars), "truncated": truncated}
