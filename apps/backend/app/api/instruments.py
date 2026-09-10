"""GET /api/instruments — 证券主数据批量查询（instrument_master）。

供 quant 等消费方批量取证券简称（ST 判定用中文名）等主数据；
quote_snapshots 只覆盖 tracked 报价池，instrument_master 覆盖全市场。
"""
from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import Field

from app.api._service_auth import ServiceIdentity, read_access
from app.db import get_pool

logger = logging.getLogger(__name__)
router = APIRouter()

Symbol = Annotated[str, Field(pattern=r"^[A-Z0-9.\-]{1,20}$")]


@router.get("/api/instruments")
async def get_instruments(
    symbols: Annotated[list[Symbol], Query(min_length=1, max_length=500)],
    identity: ServiceIdentity = Depends(read_access),
):
    """批量查询证券主数据（symbol, name, asset, market），按 symbol 升序。

    优雅降级：DB 异常记日志返回空 instruments，不 500。
    """
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT DISTINCT ON (symbol) symbol, name, asset, market
                FROM instrument_master
                WHERE symbol = ANY($1::text[])
                ORDER BY symbol, source
                """,
                symbols,
            )
    except Exception:  # noqa: BLE001
        logger.exception("/api/instruments 查询失败（consumer=%s）", identity.name)
        return {"instruments": [], "count": 0}
    instruments = [
        {
            "symbol": r["symbol"],
            "name": r["name"],
            "asset": r["asset"],
            "market": r["market"],
        }
        for r in rows
    ]
    return {"instruments": instruments, "count": len(instruments)}
