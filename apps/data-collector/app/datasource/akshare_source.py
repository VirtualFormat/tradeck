"""akshare 薄门面：进程级全局限流 + 退避重试 + 统一降级。

定时任务 / 冷启动预热 / 未来主动 load 共享同一进程级信号量，
把散落在各 job 的硬编码 sleep + try/except 收口到一处横切。
门面只做路由 + 横切，不统一 schema（各源字段仍在 job 内转换）。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Callable, TypeVar

logger = logging.getLogger(__name__)

# 进程级全局闸：所有 akshare 调用共享同一并发上限（防东财封 IP）
_sem = asyncio.Semaphore(4)

T = TypeVar("T")


async def call_akshare(
    fn: Callable[[], T],
    *,
    retries: int = 2,
    base_delay: float = 0.5,
    backoff: float = 1.5,
    throttle: float = 0.5,
) -> T:
    """在全局信号量 + 线程池中执行同步 akshare 调用。

    - 并发受 `_sem` 限制（≤4）。
    - 异常时指数退避重试（base_delay * backoff ** attempt）。
    - 成功后 throttle 节流，平滑请求节奏。

    调用方保留自己的 try/except 降级：本函数重试耗尽后仍抛出最后异常，
    由 job 决定返回空 results / 保留旧快照。
    """
    async with _sem:
        last_exc: Exception | None = None
        for attempt in range(retries + 1):
            try:
                r = await asyncio.to_thread(fn)
                if throttle:
                    await asyncio.sleep(throttle)
                return r
            except Exception as e:  # noqa: BLE001 — 退避重试所有异常
                last_exc = e
                if attempt < retries:
                    await asyncio.sleep(base_delay * backoff ** attempt)
        assert last_exc is not None
        raise last_exc
