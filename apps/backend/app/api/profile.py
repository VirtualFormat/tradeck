"""GET /api/profile — 从 equity_profiles 读"""
from __future__ import annotations

from fastapi import APIRouter, Query
from app.db import get_pool

router = APIRouter()


@router.get("/api/profile")
async def get_profile(symbol: str = Query(...)):
    """获取公司信息。"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT symbol, name, sector, industry, market_cap, currency, exchange, description
            FROM equity_profiles
            WHERE symbol = $1
            """,
            symbol.upper(),
        )

    if not row:
        return None

    return {
        "symbol": row["symbol"],
        "name": row["name"],
        "sector": row["sector"],
        "industry": row["industry"],
        "market_cap": row["market_cap"],
        "currency": row["currency"],
        "exchange": row["exchange"],
        "description": row["description"],
        "ceo": None,
        "employees": None,
        "website": None,
    }
