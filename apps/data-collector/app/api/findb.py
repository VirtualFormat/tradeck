"""findb 直连代理端点：消费方经 collector 直连 findb（不采集、不入库）。

数据流：消费方 → collector /api/findb/* → findb_source → findb API。
findb 是主数据源（A股全市场 + 复权 + 分钟K + 85 表），本端点仅做
「鉴权 + 退避 + 降级」的薄转发，业务语义由 findb_source 处理。

铁律：findb 调用收敛在 collector（数据源头面归属）；data-api 不直接调 findb，
经本端点转发（保持 data-api 零外部源）。
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Query

from app.datasource import findb_source

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/api/findb/health")
async def findb_health():
    """findb 连通性与密钥有效性探活（不消耗配额）。"""
    ok = await findb_source.health()
    return {"ok": ok, "configured": findb_source._available()}


@router.get("/api/findb/bars")
async def get_bars(
    code: str = Query(...),
    freq: str = Query("daily"),
    adjust: str = Query(""),
    start: str | None = Query(None),
    end: str | None = Query(None),
    order: str = Query("asc"),
    limit: int | None = Query(None),
):
    """直连 findb K 线（qfq/hfq 复权、分钟K）。返回扁平数组。"""
    return await findb_source.fetch_bars(
        code, freq=freq, adjust=adjust, start=start, end=end, order=order, limit=limit
    )


@router.get("/api/findb/table")
async def get_table(
    name: str = Query(...),
    cols: str | None = Query(None),
    col: str | None = Query(None),
    val: str | None = Query(None),
    sort: str | None = Query(None),
    order: str | None = Query(None),
    limit: int | None = Query(None),
):
    """直连 findb 通用取数（85 表：基本面/资金面/情绪/宏观等）。"""
    return await findb_source.fetch_table(
        name, cols=cols, col=col, val=val, sort=sort, order=order, limit=limit
    )


@router.get("/api/findb/symbols")
async def get_symbols(asset: str | None = Query(None)):
    """直连 findb 标的列表。"""
    return await findb_source.fetch_symbols(asset)


@router.get("/api/findb/coverage")
async def get_coverage(code: str = Query(...)):
    """直连 findb 标的覆盖区间（取数前确认避免取空）。"""
    return await findb_source.fetch_coverage(code)
