"""证券主数据接口（instrument_master）。

- GET /api/instruments：批量取证券简称（ST 判定用中文名）等主数据；
  quote_snapshots 只覆盖 tracked 报价池，instrument_master 覆盖全市场。
- GET /api/universe：全市场标的清单（universe 档位展开用，如 quant 的
  universe=cn 回测 A 股全市场）。
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


@router.get("/api/universe")
async def get_universe(
    market: Annotated[str, Query(pattern="^(CN|US|HK)$")],
    identity: ServiceIdentity = Depends(read_access),
):
    """全市场标的清单：instrument_master 按 asset='stock' + market 过滤。

    优雅降级：DB 异常记日志返回空 symbols，不 500（quant 侧回退 tracked 子集）。
    """
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT DISTINCT symbol
                FROM instrument_master
                WHERE asset = 'stock' AND market = $1
                ORDER BY symbol
                """,
                market,
            )
    except Exception:  # noqa: BLE001
        logger.exception("/api/universe 查询失败（market=%s）", market)
        return {"symbols": [], "count": 0, "market": market}
    symbols = [r["symbol"] for r in rows]
    return {"symbols": symbols, "count": len(symbols), "market": market}


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
