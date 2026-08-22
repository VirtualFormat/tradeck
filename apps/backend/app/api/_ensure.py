"""读 API 的按需回源助手：DB 无数据时经 collector 的 /api/ondemand 回源
（首访 2-5s，此后读库）。data-api 不直接 import job、不碰外部源——
外部调用与写库全部收敛在 data-collector（单一写者）。

- 防踩踏锁与重试隔离在 collector 侧（api/ondemand.py），data-api 只做转发
- symbol 白名单校验，防止任意字符串触发外部调用
- 失败静默（调用方重读库仍空则走空态，下次访问/下周期再试）
"""
from __future__ import annotations

import logging
import re

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_SYMBOL_RE = re.compile(r"^[A-Z0-9.\-]{1,20}$")


def valid_symbol(symbol: str) -> bool:
    return bool(_SYMBOL_RE.fullmatch(symbol))


async def ensure(kind: str, symbols: list[str]) -> None:
    """经 collector 按需回源；collector 不可达/超时记日志不抛（读路由优雅降级）。"""
    url = f"{settings.COLLECTOR_API_URL.rstrip('/')}/api/ondemand/{kind}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(url, json={"symbols": symbols})
    except Exception as e:  # noqa: BLE001
        logger.warning(f"on-demand fetch {kind}:{symbols} failed: {e}")
