"""GET /api/historical — 从 daily_prices 读"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query

from app.api._service_auth import read_access
from app.db import get_pool

# 全文件读接口统一挂 read_access（配置 SERVICE_TOKENS 后强制 X-Service-Token）
router = APIRouter(dependencies=[Depends(read_access)])


def _parse_date(s: str) -> date:
    """YYYY-MM-DD → date"""
    return date.fromisoformat(s)


@router.get("/api/historical")
async def get_historical(
    symbol: str = Query(...),
    start: str = Query(..., alias="start_date"),
    end: str = Query(..., alias="end_date"),
):
    """获取日 K 线。返回扁平数组。"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT date, open, high, low, close, volume
            FROM daily_prices
            WHERE symbol = $1 AND date BETWEEN $2 AND $3
            ORDER BY date ASC
            """,
            symbol.upper(),
            _parse_date(start),
            _parse_date(end),
        )

    return [
        {
            "date": r["date"].isoformat() if r["date"] else None,
            "open": float(r["open"]) if r["open"] else 0,
            "high": float(r["high"]) if r["high"] else 0,
            "low": float(r["low"]) if r["low"] else 0,
            "close": float(r["close"]) if r["close"] else 0,
            "volume": r["volume"] or 0,
        }
        for r in rows
    ]
