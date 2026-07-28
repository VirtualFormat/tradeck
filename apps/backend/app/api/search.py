"""GET /api/search — 按代码/名称搜索标的（equity_profiles，全市场 ~1.9 万只）"""
from __future__ import annotations

from fastapi import APIRouter, Query

from app.db import get_pool
from app.markets import pick_market

router = APIRouter()


@router.get("/api/search")
async def search_symbols(
    q: str = Query(..., min_length=1),
    limit: int = Query(10, ge=1, le=50),
):
    """搜索标的：精确代码 > 代码前缀 > 名称前缀 > 名称包含；市值大者优先。返回扁平数组。"""
    # 去通配符防 ILIKE 注入（%/_）
    kw = q.strip().replace("%", "").replace("_", "")
    if not kw:
        return []

    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT symbol, name,
                   CASE
                     WHEN upper(symbol) = upper($1) THEN 0
                     WHEN upper(symbol) LIKE upper($1) || '%' THEN 1
                     WHEN name ILIKE $1 || '%' THEN 2
                     ELSE 3
                   END AS rank
            FROM equity_profiles
            WHERE name ILIKE '%' || $1 || '%'
               OR symbol ILIKE '%' || $1 || '%'
            ORDER BY rank, market_cap DESC NULLS LAST, symbol
            LIMIT $2
            """,
            kw,
            limit,
        )

    return [
        {
            "symbol": r["symbol"],
            "name": r["name"],
            "market": pick_market(r["symbol"]),
        }
        for r in rows
    ]
