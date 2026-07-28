"""读 API 的按需回源助手：DB 无数据时经 job 拉取函数现拉写库（首访 2-5s，此后读库）。

- per-key asyncio.Lock 合并同键并发（同一标的的并发请求防踩踏打源）
- symbol 白名单校验，防止任意字符串触发外部调用
- 失败静默（调用方重读库仍空则走空态，下次访问/下周期再试）
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Awaitable, Callable

logger = logging.getLogger(__name__)

_SYMBOL_RE = re.compile(r"^[A-Z0-9.\-]{1,20}$")

_locks: dict[str, asyncio.Lock] = {}


def valid_symbol(symbol: str) -> bool:
    return bool(_SYMBOL_RE.fullmatch(symbol))


async def ensure(key: str, fetch: Callable[[], Awaitable[object]]) -> None:
    """per-key 锁内执行按需拉取；失败记日志不抛。"""
    lock = _locks.setdefault(key, asyncio.Lock())
    async with lock:
        try:
            await fetch()
        except Exception as e:  # noqa: BLE001
            logger.warning(f"on-demand fetch {key} failed: {e}")
