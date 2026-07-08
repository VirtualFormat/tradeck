"""GET /api/movers — 从 movers_cache 读"""
from __future__ import annotations

from fastapi import APIRouter, Query
from app.db import get_pool

router = APIRouter()


@router.get("/api/movers")
async def get_movers(
    type: str = Query("gainers"),
    market: str = Query("US"),
    limit: int = Query(10),
):
    """获取涨跌榜。type: gainers/losers/active"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT rank, symbol, name, price, percent_change, volume
            FROM movers_cache
            WHERE type = $1 AND market = $2
            ORDER BY rank ASC
            LIMIT $3
            """,
            type,
            market.upper(),
            limit,
        )

    return [
        {
            "symbol": r["symbol"],
            "name": r["name"],
            "price": float(r["price"]) if r["price"] else None,
            "change": None,
            "percent_change": float(r["percent_change"]) if r["percent_change"] else None,
            "volume": r["volume"],
            "exchange": None,
        }
        for r in rows
    ]
