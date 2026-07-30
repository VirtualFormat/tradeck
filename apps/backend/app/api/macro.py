"""GET /api/macro — 从 macro_indicators 读"""
from __future__ import annotations

from fastapi import APIRouter, Query
from app.db import get_pool

router = APIRouter()


@router.get("/api/macro")
async def get_macro(
    name: str = Query(None),
    limit: int = Query(12),
):
    """获取宏观指标。不传 name 返回所有指标最新值。"""
    pool = await get_pool()

    if name:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT name, date, value
                FROM macro_indicators
                WHERE name = $1
                ORDER BY date DESC
                LIMIT $2
                """,
                name,
                limit,
            )
        # 按日期升序返回（前端画图用）
        rows = list(reversed(rows))
        return [
            {
                "date": r["date"].isoformat() if r["date"] else None,
                "value": float(r["value"]) if r["value"] is not None else None,
                "country": None,
            }
            for r in rows
        ]

    # 返回所有指标最新值
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT DISTINCT ON (name) name, date, value
            FROM macro_indicators
            ORDER BY name, date DESC
            """
        )

    return [
        {
            "name": r["name"],
            "date": r["date"].isoformat() if r["date"] else None,
            "value": float(r["value"]) if r["value"] is not None else None,
        }
        for r in rows
    ]
