"""GET /api/fundflow — 个股资金流向榜（从 fund_flow 读）"""
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


@router.get("/api/fundflow")
async def get_fund_flow(
    direction: str = Query("in"),
    limit: int = Query(10),
    date: str | None = Query(None),
):
    """个股资金流向榜。direction: in 净流入红榜 / out 净流出绿榜；date: YYYY-MM-DD（默认最近快照日）"""
    direction_sql = "ASC" if direction.lower() == "out" else "DESC"
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT symbol, name, price, change_percent, turnover_rate,
                   amount_in, amount_out, net_amount, amount_total, updated_at
            FROM fund_flow
            WHERE net_amount IS NOT NULL
              AND snapshot_date = COALESCE($2::date, (SELECT max(snapshot_date) FROM fund_flow))
            ORDER BY net_amount {direction_sql}
            LIMIT $1
            """,
            limit,
            _parse_date(date),
        )

    return [
        {
            "symbol": r["symbol"],
            "name": r["name"],
            "price": float(r["price"]) if r["price"] else None,
            "change_percent": float(r["change_percent"]) if r["change_percent"] else None,
            "turnover_rate": float(r["turnover_rate"]) if r["turnover_rate"] else None,
            "amount_in": r["amount_in"],
            "amount_out": r["amount_out"],
            "net_amount": r["net_amount"],
            "amount_total": r["amount_total"],
            "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
        }
        for r in rows
    ]
