"""GET /api/news — 从 news_articles 读"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api._service_auth import read_access
from app.db import get_pool

# 全文件读接口统一挂 read_access（配置 SERVICE_TOKENS 后强制 X-Service-Token）
router = APIRouter(dependencies=[Depends(read_access)])


@router.get("/api/news")
async def get_news(
    symbol: str = Query(None),
    limit: int = Query(20),
):
    """获取新闻。不传 symbol 返回最新新闻。"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        if symbol:
            rows = await conn.fetch(
                """
                SELECT symbol, title, url, summary, publisher, published_at
                FROM news_articles
                WHERE symbol = $1
                ORDER BY published_at DESC NULLS LAST
                LIMIT $2
                """,
                symbol.upper(),
                limit,
            )
        else:
            rows = await conn.fetch(
                """
                SELECT symbol, title, url, summary, publisher, published_at
                FROM news_articles
                ORDER BY published_at DESC NULLS LAST
                LIMIT $1
                """,
                limit,
            )

    return [
        {
            "symbol": r["symbol"],
            "title": r["title"],
            "url": r["url"],
            "summary": r["summary"],
            "publisher": r["publisher"],
            "date": r["published_at"].isoformat() if r["published_at"] else None,
            "source": r["publisher"],
            "text": None,
            "symbols": None,
        }
        for r in rows
    ]
