"""GET /api/profile — 从 equity_profiles 读；无数据时经 collector 按需回源"""
from __future__ import annotations

from fastapi import APIRouter, Query

from app.api._ensure import ensure, valid_symbol
from app.db import get_pool

router = APIRouter()


async def _fetch_row(pool, symbol: str):
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            """
            SELECT symbol, name, sector, industry, market_cap, currency, exchange, description
            FROM equity_profiles
            WHERE symbol = $1
            """,
            symbol,
        )


@router.get("/api/profile")
async def get_profile(symbol: str = Query(...)):
    """获取公司信息。DB 无（或仅名称占位行）时经 collector 按需回源（首访 2-5s，此后读库）。"""
    sym = symbol.upper()
    pool = await get_pool()
    row = await _fetch_row(pool, sym)
    # 无行或仅 instruments 名称占位行（无 sector/市值）→ 按需回源补拉
    if (
        row is None or (row["sector"] is None and row["market_cap"] is None)
    ) and valid_symbol(sym):
        await ensure("profile", [sym])
        row = await _fetch_row(pool, sym)

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
