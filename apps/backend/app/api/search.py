"""GET /api/search — 按代码/名称搜索标的（equity_profiles，全市场 ~1.9 万只）"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api._service_auth import read_access
from app.db import get_pool
from app.markets import pick_market

# 全文件读接口统一挂 read_access（配置 SERVICE_TOKENS 后强制 X-Service-Token）
router = APIRouter(dependencies=[Depends(read_access)])


@router.get("/api/search/validate")
async def validate_symbols(
    symbols: str = Query(..., description="逗号分隔的规范股票代码"),
):
    """批量校验股票代码是否存在于已知全市场标的库。"""
    sym_list = list(
        dict.fromkeys(s.strip().upper() for s in symbols.split(",") if s.strip())
    )[:100]
    if not sym_list:
        return []

    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT symbol
            FROM equity_profiles
            WHERE symbol = ANY($1::text[])
            UNION
            SELECT DISTINCT symbol
            FROM daily_prices
            WHERE symbol = ANY($1::text[])
            UNION
            SELECT symbol
            FROM quote_snapshots
            WHERE symbol = ANY($1::text[])
            """,
            sym_list,
        )
    valid = {r["symbol"] for r in rows}
    return [{"symbol": symbol} for symbol in sym_list if symbol in valid]


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
