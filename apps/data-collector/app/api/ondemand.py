"""POST /api/ondemand/{kind} — 按需回源入口。

data-api 读路由在 DB 无数据时调用本端点，由 collector（唯一写者）现拉
外部数据源并写库；data-api 自身不再 import job、不碰外部源。

- kind 白名单映射到 job 函数（模块级 dict），未登记的 kind 直接 404
- per-key asyncio.Lock 合并同键并发（同一标的的并发请求防踩踏打源）
- symbol 白名单校验，防止任意字符串触发外部调用
- job 失败记日志不抛（优雅降级；data-api 重读库仍空则走空态，下周期再试）
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import date
from typing import Awaitable, Callable

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.jobs.analyst_consensus import fetch_and_store_consensus
from app.jobs.fundamentals import (
    fetch_and_store_balance,
    fetch_and_store_cash,
    fetch_and_store_income,
    fetch_and_store_metrics,
    fetch_and_store_profile,
)
from app.jobs.realtime_quotes import fetch_and_store_quotes

logger = logging.getLogger(__name__)

router = APIRouter()

_SYMBOL_RE = re.compile(r"^[A-Z0-9.\-]{1,20}$")

_locks: dict[str, asyncio.Lock] = {}

# kind → job 调用（quotes 批量，其余单只取 symbols[0]）
_HANDLERS: dict[str, Callable[[list[str]], Awaitable[int]]] = {
    "quotes": lambda syms: fetch_and_store_quotes(syms),
    "profile": lambda syms: fetch_and_store_profile(syms[0]),
    "metrics": lambda syms: fetch_and_store_metrics(syms[0]),
    "income": lambda syms: fetch_and_store_income(syms[0]),
    "balance": lambda syms: fetch_and_store_balance(syms[0]),
    "cash": lambda syms: fetch_and_store_cash(syms[0]),
    "consensus": lambda syms: fetch_and_store_consensus(syms[0], date.today()),
}


class OnDemandRequest(BaseModel):
    symbols: list[str] = Field(..., min_length=1, max_length=50)


@router.post("/api/ondemand/{kind}")
async def on_demand(kind: str, body: OnDemandRequest):
    handler = _HANDLERS.get(kind)
    if handler is None:
        raise HTTPException(status_code=404, detail=f"unknown on-demand kind: {kind}")

    symbols = [s.strip().upper() for s in body.symbols if s.strip()]
    if not symbols or not all(_SYMBOL_RE.fullmatch(s) for s in symbols):
        raise HTTPException(status_code=400, detail="invalid symbols")

    key = f"{kind}:{','.join(sorted(symbols))}"
    lock = _locks.setdefault(key, asyncio.Lock())
    async with lock:
        try:
            await handler(symbols)
        except Exception as e:  # noqa: BLE001 — 优雅降级，不回 500
            logger.warning("on-demand fetch %s failed: %s", key, e)
            return {"ok": False}
    return {"ok": True}
