"""GET /api/boards/heat — 板块行情热度（从 board_heat 读）"""
from __future__ import annotations

from datetime import date as date_type

from fastapi import APIRouter, Depends, Query

from app.api._service_auth import read_access
from app.db import get_pool

# 全文件读接口统一挂 read_access（配置 SERVICE_TOKENS 后强制 X-Service-Token）
router = APIRouter(dependencies=[Depends(read_access)])


def _parse_date(s: str | None) -> date_type | None:
    """YYYY-MM-DD 字符串 → date 对象（asyncpg 不接受字符串）"""
    if not s:
        return None
    try:
        return date_type.fromisoformat(s[:10])
    except ValueError:
        return None


@router.get("/api/boards/heat")
async def get_board_heat(
    type: str = Query("industry"),
    limit: int = Query(80),
    order: str = Query("change"),
    date: str | None = Query(None),
):
    """板块行情热度。order: change 按涨幅 / market_cap 按市值。"""
    order_sql = (
        "market_cap DESC NULLS LAST"
        if order.lower() == "market_cap"
        else "change_percent DESC NULLS LAST"
    )
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT name, code, change_percent, market_cap, turnover_rate,
                   leader_stock, leader_change, snapshot_date
            FROM board_heat
            WHERE board_type = $1
              AND snapshot_date = COALESCE($3::date, (SELECT max(snapshot_date) FROM board_heat WHERE board_type = $1))
            ORDER BY {order_sql}
            LIMIT $2
            """,
            type,
            limit,
            _parse_date(date),
        )

    return [
        {
            "name": r["name"],
            "code": r["code"],
            "change_percent": float(r["change_percent"]) if r["change_percent"] else None,
            "market_cap": r["market_cap"],
            "turnover_rate": float(r["turnover_rate"]) if r["turnover_rate"] else None,
            "leader_stock": r["leader_stock"],
            "leader_change": float(r["leader_change"]) if r["leader_change"] else None,
            "snapshot_date": r["snapshot_date"].isoformat() if r["snapshot_date"] else None,
            "source": "ths" if (r["code"] or "").startswith("THS:") else "eastmoney",
            "size_basis": "turnover" if (r["code"] or "").startswith("THS:") else "market_cap",
        }
        for r in rows
    ]


@router.get("/api/boards/sentiment")
async def get_board_sentiment(
    type: str = Query("industry"),
    limit: int = Query(20),
    order: str = Query("desc"),
    date: str | None = Query(None),
):
    """板块舆情热度榜（24h 新闻量 + 情绪均值 + 综合热度）。order: desc 最热 / asc 最冷；date: YYYY-MM-DD（默认最近快照日）"""
    direction = "ASC" if order.lower() == "asc" else "DESC"
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT board_name, news_count_24h, sentiment_avg, hot_score, updated_at
            FROM board_sentiment
            WHERE board_type = $1
              AND snapshot_date = COALESCE($3::date, (SELECT max(snapshot_date) FROM board_sentiment WHERE board_type = $1))
            ORDER BY hot_score {direction} NULLS LAST
            LIMIT $2
            """,
            type,
            limit,
            _parse_date(date),
        )

    return [
        {
            "name": r["board_name"],
            "news_count": r["news_count_24h"],
            "sentiment_avg": float(r["sentiment_avg"]) if r["sentiment_avg"] else None,
            "hot_score": float(r["hot_score"]) if r["hot_score"] else None,
            "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
        }
        for r in rows
    ]
