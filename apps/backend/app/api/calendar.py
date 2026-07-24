"""GET /api/calendar/* — 财报日历 + 宏观数据日历（从 earnings_calendar / economic_calendar 读）"""
from __future__ import annotations

from fastapi import APIRouter, Query
from app.db import get_pool

router = APIRouter()


@router.get("/api/calendar/earnings")
async def get_earnings_calendar(
    days: int = Query(14),
    symbol: str | None = Query(None),
):
    """财报日历：今天起 days 天内的财报披露事件，按日期升序。symbol 可选过滤。"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        if symbol:
            rows = await conn.fetch(
                """
                SELECT symbol, report_date, session, eps_estimate, source
                FROM earnings_calendar
                WHERE report_date >= CURRENT_DATE
                  AND report_date <= CURRENT_DATE + $1::int
                  AND symbol = $2
                ORDER BY report_date ASC, symbol ASC
                """,
                days,
                symbol.upper(),
            )
        else:
            rows = await conn.fetch(
                """
                SELECT symbol, report_date, session, eps_estimate, source
                FROM earnings_calendar
                WHERE report_date >= CURRENT_DATE
                  AND report_date <= CURRENT_DATE + $1::int
                ORDER BY report_date ASC, symbol ASC
                """,
                days,
            )

    return [
        {
            "symbol": r["symbol"],
            "report_date": r["report_date"].isoformat() if r["report_date"] else None,
            "session": r["session"],
            "eps_estimate": float(r["eps_estimate"]) if r["eps_estimate"] is not None else None,
            "source": r["source"],
        }
        for r in rows
    ]


@router.get("/api/calendar/economic")
async def get_economic_calendar(days: int = Query(7)):
    """宏观数据日历：今天起 days 天内的经济数据发布事件，按日期升序。"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT event_date, event_time, country, event_name, importance,
                   actual, forecast, previous, source
            FROM economic_calendar
            WHERE event_date >= CURRENT_DATE
              AND event_date <= CURRENT_DATE + $1::int
            ORDER BY event_date ASC, event_time ASC NULLS LAST
            """,
            days,
        )

    return [
        {
            "event_date": r["event_date"].isoformat() if r["event_date"] else None,
            "event_time": r["event_time"],
            "country": r["country"],
            "event_name": r["event_name"],
            "importance": r["importance"],
            "actual": r["actual"],
            "forecast": r["forecast"],
            "previous": r["previous"],
            "source": r["source"],
        }
        for r in rows
    ]
