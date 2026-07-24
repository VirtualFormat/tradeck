"""GET /api/technicals — 从 technical_indicators 读"""
from __future__ import annotations

from fastapi import APIRouter, Query
from app.db import get_pool

router = APIRouter()


def _f(v) -> float | None:
    return float(v) if v is not None else None


@router.get("/api/technicals")
async def get_technicals(
    symbol: str = Query(...),
    days: int = Query(120, ge=1, le=500),
):
    """获取技术指标，按日期升序（方便画图）。返回扁平数组。"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT date, ma5, ma10, ma20, ma60, ema12, ema26,
                   dif, dea, macd, rsi6, rsi14, boll_upper, boll_mid, boll_lower
            FROM technical_indicators
            WHERE symbol = $1
            ORDER BY date DESC
            LIMIT $2
            """,
            symbol.upper(),
            days,
        )

    return [
        {
            "date": r["date"].isoformat() if r["date"] else None,
            "ma5": _f(r["ma5"]),
            "ma10": _f(r["ma10"]),
            "ma20": _f(r["ma20"]),
            "ma60": _f(r["ma60"]),
            "ema12": _f(r["ema12"]),
            "ema26": _f(r["ema26"]),
            "dif": _f(r["dif"]),
            "dea": _f(r["dea"]),
            "macd": _f(r["macd"]),
            "rsi6": _f(r["rsi6"]),
            "rsi14": _f(r["rsi14"]),
            "boll_upper": _f(r["boll_upper"]),
            "boll_mid": _f(r["boll_mid"]),
            "boll_lower": _f(r["boll_lower"]),
        }
        for r in reversed(rows)  # 升序返回
    ]
