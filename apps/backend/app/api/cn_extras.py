"""A 股补充数据路由：/api/announcements、/api/research、/api/breadth

- announcements：tracked A 股公告（东财，announcements 表）
- research：单只 A 股券商研报（东财，research_reports 表）
- breadth：A 股市场宽度（乐咕，market_breadth 表）
全部返回扁平数组。
"""
from __future__ import annotations

from fastapi import APIRouter, Query

from app.db import get_pool
from app.jobs.daily_kline import TRACKED_SYMBOLS
from app.markets import pick_market

router = APIRouter()

# tracked A 股（announcements 不带 symbol 时默认查全体）
_CN_SYMBOLS = [s for s in TRACKED_SYMBOLS if pick_market(s) == "CN"]


@router.get("/api/announcements")
async def get_announcements(
    symbol: str | None = Query(None),
    days: int = Query(30),
):
    """A 股公告，按发布日期倒序。不带 symbol 返回 tracked 全体 A 股。"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        if symbol:
            rows = await conn.fetch(
                """
                SELECT symbol, title, category, publish_date, url
                FROM announcements
                WHERE symbol = $1
                  AND publish_date >= CURRENT_DATE - make_interval(days => $2)
                ORDER BY publish_date DESC, fetched_at DESC
                """,
                symbol,
                days,
            )
        else:
            rows = await conn.fetch(
                """
                SELECT symbol, title, category, publish_date, url
                FROM announcements
                WHERE symbol = ANY($1::text[])
                  AND publish_date >= CURRENT_DATE - make_interval(days => $2)
                ORDER BY publish_date DESC, fetched_at DESC
                """,
                _CN_SYMBOLS,
                days,
            )
    return [
        {
            "symbol": r["symbol"],
            "title": r["title"],
            "category": r["category"],
            "publish_date": r["publish_date"].isoformat() if r["publish_date"] else None,
            "url": r["url"],
        }
        for r in rows
    ]


@router.get("/api/research")
async def get_research_reports(
    symbol: str = Query(...),
    days: int = Query(90),
):
    """单只 A 股券商研报，按发布日期倒序。"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT symbol, title, org, rating, industry,
                   eps_forecast, pe_forecast, forecast_year, publish_date, url
            FROM research_reports
            WHERE symbol = $1
              AND publish_date >= CURRENT_DATE - make_interval(days => $2)
            ORDER BY publish_date DESC, fetched_at DESC
            """,
            symbol,
            days,
        )
    return [
        {
            "symbol": r["symbol"],
            "title": r["title"],
            "org": r["org"],
            "rating": r["rating"],
            "industry": r["industry"],
            "eps_forecast": float(r["eps_forecast"]) if r["eps_forecast"] is not None else None,
            "pe_forecast": float(r["pe_forecast"]) if r["pe_forecast"] is not None else None,
            "forecast_year": r["forecast_year"],
            "publish_date": r["publish_date"].isoformat() if r["publish_date"] else None,
            "url": r["url"],
        }
        for r in rows
    ]


@router.get("/api/breadth")
async def get_market_breadth(
    days: int = Query(60),
    market: str = Query("CN"),
):
    """市场宽度时间序列，按日期升序（末元素即最新快照）。"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT date, market, up_count, down_count, flat_count,
                   limit_up_count, limit_down_count,
                   real_limit_up_count, real_limit_down_count,
                   suspended_count, activity_rate, source
            FROM market_breadth
            WHERE market = $1
              AND date >= CURRENT_DATE - make_interval(days => $2)
            ORDER BY date ASC
            """,
            market,
            days,
        )
    return [
        {
            "date": r["date"].isoformat() if r["date"] else None,
            "market": r["market"],
            "up_count": r["up_count"],
            "down_count": r["down_count"],
            "flat_count": r["flat_count"],
            "limit_up_count": r["limit_up_count"],
            "limit_down_count": r["limit_down_count"],
            "real_limit_up_count": r["real_limit_up_count"],
            "real_limit_down_count": r["real_limit_down_count"],
            "suspended_count": r["suspended_count"],
            "activity_rate": float(r["activity_rate"]) if r["activity_rate"] is not None else None,
        }
        for r in rows
    ]
