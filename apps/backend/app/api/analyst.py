"""GET /api/analyst — 从 analyst_consensus 读"""
from __future__ import annotations

from fastapi import APIRouter, Query
from app.db import get_pool

router = APIRouter()


@router.get("/api/analyst/consensus")
async def get_consensus(symbol: str = Query(...)):
    """获取最新一条分析师共识/目标价。无数据返回 null。"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT symbol, snapshot_date, recommendation, recommendation_mean,
                number_of_analysts, target_high, target_low, target_consensus,
                target_median, current_price, currency
            FROM analyst_consensus
            WHERE symbol = $1
            ORDER BY snapshot_date DESC
            LIMIT 1
            """,
            symbol.upper(),
        )

    if not row:
        return None

    def _f(v):
        return float(v) if v is not None else None

    return {
        "symbol": row["symbol"],
        "snapshot_date": row["snapshot_date"].isoformat() if row["snapshot_date"] else None,
        "recommendation": row["recommendation"],
        "recommendation_mean": _f(row["recommendation_mean"]),
        "number_of_analysts": row["number_of_analysts"],
        "target_high": _f(row["target_high"]),
        "target_low": _f(row["target_low"]),
        "target_consensus": _f(row["target_consensus"]),
        "target_median": _f(row["target_median"]),
        "current_price": _f(row["current_price"]),
        "currency": row["currency"],
    }
