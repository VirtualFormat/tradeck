"""findb 直连路由（data-api 侧）：复权 K 线 / 分钟K / 85 表。

数据流：消费方 → data-api /api/findb/* → collector /api/findb/* → findb API。
findb 是主数据源（A股全市场 + 复权 qfq/hfq + 分钟K），data-api 不直接调 findb，
经 collector 转发（保持 data-api 零外部源铁律，findb 调用收敛在 collector）。

与读库的 /api/bars（批量日K）区分：本路由是 findb 直连（实时、复权、分钟K），
单 code；/api/bars 是 PG 批量历史（日K 原始价）。
"""
from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, Query

from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter()


async def _collector_findb(path: str, params: dict) -> object:
    """转发到 collector 的 findb 端点；失败优雅降级返回空。"""
    url = f"{settings.COLLECTOR_API_URL.rstrip('/')}/api/findb{path}"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            res = await client.get(url, params={k: v for k, v in params.items() if v is not None})
            return res.json() if res.status_code == 200 else []
    except Exception as e:  # noqa: BLE001
        logger.warning(f"findb 转发失败 {path}: {e}")
        return []


@router.get("/api/findb/bars")
async def get_findb_bars(
    code: str = Query(..., description="带后缀代码，如 600036.SH / AAPL.US / 00700.HK"),
    freq: str = Query("daily", description="1min/5min/15min/30min/60min/daily"),
    adjust: str = Query("", description="复权：空=原始 / qfq 前复权 / hfq 后复权"),
    start: str | None = Query(None),
    end: str | None = Query(None),
    order: str = Query("asc"),
    limit: int | None = Query(None),
):
    """findb K 线直连（复权 qfq/hfq + 分钟K + A股全市场）。

    复权语义：adjust 空=原始价、qfq=前复权（以最新日基准）、hfq=后复权（以最早日基准）。
    「最近 N 根」须 order=desc（findb 约定）。
    """
    return await _collector_findb(
        "/bars",
        {"code": code, "freq": freq, "adjust": adjust, "start": start, "end": end, "order": order, "limit": limit},
    )


@router.get("/api/findb/table")
async def get_findb_table(
    name: str = Query(...),
    cols: str | None = Query(None),
    col: str | None = Query(None),
    val: str | None = Query(None),
    sort: str | None = Query(None),
    order: str | None = Query(None),
    limit: int | None = Query(None),
):
    """findb 通用取数（85 表：基本面/资金面/情绪/宏观/复权因子 adj_factor 等）。"""
    return await _collector_findb(
        "/table",
        {"name": name, "cols": cols, "col": col, "val": val, "sort": sort, "order": order, "limit": limit},
    )


@router.get("/api/findb/symbols")
async def get_findb_symbols(asset: str | None = Query(None)):
    """findb 标的列表（asset: stock/etf/future/us_stock/hk_stock/index/...）。"""
    return await _collector_findb("/symbols", {"asset": asset})


@router.get("/api/findb/coverage")
async def get_findb_coverage(code: str = Query(...)):
    """findb 标的覆盖区间（取数前确认避免取空）。"""
    return await _collector_findb("/coverage", {"code": code})
