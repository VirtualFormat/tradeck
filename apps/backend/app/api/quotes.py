"""GET /api/quotes — 从 quote_snapshots 读"""
from __future__ import annotations

from fastapi import APIRouter, Query
from app.db import get_pool

router = APIRouter()


@router.get("/api/quotes")
async def get_quotes(symbols: str = Query(..., description="逗号分隔的股票代码")):
    """批量获取报价。返回扁平数组（非 OpenBB 的 { results: [...] } 包裹）。"""
    if not symbols:
        return []

    sym_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    if not sym_list:
        return []

    pool = await get_pool()
    async with pool.acquire() as conn:
        # 用 ANY($1::text[]) 匹配多个 symbol
        rows = await conn.fetch(
            """
            SELECT symbol, name, last_price, change, change_percent, volume, market
            FROM quote_snapshots
            WHERE symbol = ANY($1::text[])
            """,
            sym_list,
        )

    return [
        {
            "symbol": r["symbol"],
            "name": r["name"],
            "last_price": float(r["last_price"]) if r["last_price"] else None,
            "change": float(r["change"]) if r["change"] else None,
            "change_percent": float(r["change_percent"]) if r["change_percent"] else None,
            "volume": r["volume"],
            "exchange": None,  # 兼容前端 EquityQuote 接口
            "currency": None,
            "open": None,
            "high": None,
            "low": None,
            "prev_close": None,
        }
        for r in rows
    ]
