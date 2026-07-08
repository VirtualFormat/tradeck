"""GET /api/indices — 从 index_prices 读"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Query
from app.db import get_pool

router = APIRouter()


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    return date.fromisoformat(s)


@router.get("/api/indices")
async def get_indices(
    symbol: str = Query(None),
    market: str = Query(None),
    start: str = Query(None, alias="start_date"),
    end: str = Query(None, alias="end_date"),
):
    """获取指数历史。如果不传 symbol，按 market 返回所有指数最新价。

    前端两种调用：
    1. /api/indices?symbol=^GSPC&start_date=...&end_date=... → 单指数历史
    2. /api/indices?market=us → 该市场所有指数最新价
    """
    pool = await get_pool()

    if symbol:
        # 单指数历史
        start_d = _parse_date(start) or date(1900, 1, 1)
        end_d = _parse_date(end) or date(2099, 12, 31)
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT symbol, market, date, close, volume
                FROM index_prices
                WHERE symbol = $1 AND date BETWEEN $2 AND $3
                ORDER BY date ASC
                """,
                symbol,
                start_d,
                end_d,
            )
        return [
            {
                "symbol": r["symbol"],
                "market": r["market"],
                "date": r["date"].isoformat() if r["date"] else None,
                "close": float(r["close"]) if r["close"] else None,
                "volume": r["volume"],
            }
            for r in rows
        ]

    # 按 market 返回所有指数最新价
    async with pool.acquire() as conn:
        if market:
            rows = await conn.fetch(
                """
                SELECT DISTINCT ON (symbol) symbol, market, date, close, volume
                FROM index_prices
                WHERE market = $1
                ORDER BY symbol, date DESC
                """,
                market.upper(),
            )
        else:
            rows = await conn.fetch(
                """
                SELECT DISTINCT ON (symbol) symbol, market, date, close, volume
                FROM index_prices
                ORDER BY symbol, date DESC
                """
            )

    return [
        {
            "symbol": r["symbol"],
            "market": r["market"],
            "date": r["date"].isoformat() if r["date"] else None,
            "close": float(r["close"]) if r["close"] else None,
            "volume": r["volume"],
        }
        for r in rows
    ]
