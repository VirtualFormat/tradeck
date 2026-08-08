"""GET /api/quotes — 从 quote_snapshots 读；美/港股缺失时按需回源现拉写库"""
from __future__ import annotations

from fastapi import APIRouter, Query

from app.api._ensure import ensure, valid_symbol
from app.db import get_pool
from app.jobs.realtime_quotes import fetch_and_store_quotes

router = APIRouter()


async def _fetch_rows(pool, sym_list: list[str]):
    async with pool.acquire() as conn:
        # 用 ANY($1::text[]) 匹配多个 symbol
        return await conn.fetch(
            """
            SELECT symbol, name, last_price, change, change_percent, volume,
                   market, data_as_of, updated_at
            FROM quote_snapshots
            WHERE symbol = ANY($1::text[])
            """,
            sym_list,
        )


@router.get("/api/quotes")
async def get_quotes(symbols: str = Query(..., description="逗号分隔的股票代码")):
    """批量获取报价。返回扁平数组（非 OpenBB 的 { results: [...] } 包裹）。

    美/港股缺失时按需回源 yfinance 现拉（首访 2-5s）；A 股 spot 为全市场接口，
    单标的回源太重，由 30 分钟 job 覆盖，不在此回源。
    """
    if not symbols:
        return []

    sym_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    if not sym_list:
        return []

    pool = await get_pool()
    rows = await _fetch_rows(pool, sym_list)

    found = {r["symbol"] for r in rows}
    on_demand = [
        s
        for s in sym_list
        if s not in found
        and valid_symbol(s)
        and not s.endswith((".SH", ".SS", ".SZ", ".BJ"))  # A 股不回源（见 docstring）
    ]
    if on_demand:
        await ensure(
            f"quotes:{','.join(sorted(on_demand))}",
            lambda: fetch_and_store_quotes(on_demand),
        )
        rows = await _fetch_rows(pool, sym_list)

    return [
        {
            "symbol": r["symbol"],
            "name": r["name"],
            "last_price": float(r["last_price"]) if r["last_price"] is not None else None,
            "change": float(r["change"]) if r["change"] is not None else None,
            "change_percent": float(r["change_percent"]) if r["change_percent"] is not None else None,
            "volume": r["volume"],
            "exchange": None,  # 兼容前端 EquityQuote 接口
            "currency": None,
            "open": None,
            "high": None,
            "low": None,
            "prev_close": None,
            "data_as_of": r["data_as_of"].isoformat() if r["data_as_of"] else None,
            "fetched_at": r["updated_at"].isoformat() if r["updated_at"] else None,
        }
        for r in rows
    ]
