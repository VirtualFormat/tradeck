"""GET /api/movers — 从 movers_cache 读"""
from __future__ import annotations

from datetime import date as date_type

from fastapi import APIRouter, Query
from app.db import get_pool

router = APIRouter()


def _parse_date(s: str | None) -> date_type | None:
    """YYYY-MM-DD 字符串 → date 对象（asyncpg 不接受字符串）"""
    if not s:
        return None
    try:
        return date_type.fromisoformat(s[:10])
    except ValueError:
        return None


@router.get("/api/movers")
async def get_movers(
    type: str = Query("gainers"),
    market: str = Query("US"),
    limit: int = Query(10),
    date: str | None = Query(None),
):
    """获取涨跌榜。type: gainers/losers/active；date: YYYY-MM-DD（默认最近快照日）"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT rank, symbol, name, price, percent_change, volume, amount,
                   snapshot_date, updated_at
            FROM movers_cache
            WHERE type = $1 AND market = $2
              AND snapshot_date = COALESCE(
                    $4::date,
                    (SELECT max(snapshot_date) FROM movers_cache WHERE type = $1 AND market = $2)
                  )
            ORDER BY rank ASC
            LIMIT $3
            """,
            type,
            market.upper(),
            limit,
            _parse_date(date),
        )

    return [
        {
            "symbol": r["symbol"],
            "name": r["name"],
            "price": float(r["price"]) if r["price"] else None,
            "change": None,
            "percent_change": (
                float(r["percent_change"]) if r["percent_change"] else None
            ),
            "volume": r["volume"],
            "amount": float(r["amount"]) if r["amount"] else None,
            "exchange": None,
            "snapshot_date": (
                r["snapshot_date"].isoformat() if r["snapshot_date"] else None
            ),
            "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
        }
        for r in rows
    ]


@router.get("/api/movers/turnover")
async def get_movers_turnover(
    market: str = Query("US"),
    limit: int = Query(10),
):
    """换手榜：成交额 / 市值（quote_snapshots 关联 equity_profiles，缺公司信息的标的不计）"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT q.symbol, q.name, q.last_price, q.change_percent, q.volume,
                   q.updated_at,
                   (q.volume * q.last_price / p.market_cap) AS turnover
            FROM quote_snapshots q
            JOIN equity_profiles p ON p.symbol = q.symbol
            WHERE q.market = $1 AND p.market_cap > 0 AND q.last_price > 0
            ORDER BY turnover DESC
            LIMIT $2
            """,
            market.upper(),
            limit,
        )

    return [
        {
            "symbol": r["symbol"],
            "name": r["name"],
            "price": float(r["last_price"]) if r["last_price"] else None,
            "change": None,
            "percent_change": float(r["change_percent"]) if r["change_percent"] else None,
            "volume": r["volume"],
            "turnover": float(r["turnover"]) if r["turnover"] else None,
            "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
        }
        for r in rows
    ]
