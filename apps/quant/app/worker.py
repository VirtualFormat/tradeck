"""回测 worker 池 — spawn 子进程隔离重计算（多用户骨架 G4，docs/QUANT-BACKTEST.md v2 §0）。

设计（参照 tick-stock-panel backend/app/backtest/worker.py 的消息协议与取消语义，轻量化）：
- mp.get_context("spawn")：子进程独立解释器，崩溃/超时 terminate 后主进程不受影响。
- 消息协议：父进程 Queue 收 {"type": "progress"/"result"/"error", ...}；
  子进程把终态消息入队后 close+join_thread 冲刷管道，再 os._exit(0) 跳过解释器收尾。
- 父进程循环收消息；子进程意外退出后兜底排空队列一次（读线程可能还没把管道尾部
  搬进本地缓冲）；拿到终态消息但子进程收尾慢则 terminate 后继续处理，不丢已送达结果。
- 池大小 = QUANT_WORKER_POOL_SIZE（默认 1 = 串行）；asyncio.Semaphore 控制同时在跑的
  子进程数，回测同步计算用 asyncio.to_thread 推到线程，不阻塞事件循环。
- 与参照的差异：不做 RSS 采样、不引 psutil；不实现主动取消（量化回测秒~分钟级，
  结构化错误已保证主进程可感知）。
"""
from __future__ import annotations

import asyncio
import logging
import multiprocessing as mp
import os
import queue
import traceback
from contextlib import suppress
from dataclasses import asdict
from datetime import date
from typing import Any

logger = logging.getLogger(__name__)


class BacktestWorkerError(RuntimeError):
    """worker 子进程失败（异常/崩溃/超时未出结果）时抛出，调用方转成结构化错误响应。"""


# 子进程收尾超时：拿到终态消息后最多等 10s，否则 terminate（对齐参照口径）
_JOIN_TIMEOUT_SECONDS = 10.0

# 全局池（模块级单例；与「backend 单进程」纪律一致，quant 服务内唯一）
_pool: "WorkerPool | None" = None


def _encode_config(config) -> dict[str, Any]:
    """MatcherConfig → 可跨进程序列化的 dict。"""
    if config is None:
        return {}
    return asdict(config)


def _decode_config(payload: dict[str, Any]):
    from app.engine import MatcherConfig

    return MatcherConfig(**payload)


def make_backtest_task(
    symbols: list[str],
    strategy_id: str,
    start: date,
    end: date,
    params: dict | None = None,
    config=None,
    user_id: str | None = None,
    names: dict[str, str] | None = None,
) -> dict[str, Any]:
    """打包一次回测任务（可经 Queue 传给 spawn 子进程）。"""
    return {
        "kind": "backtest",
        "symbols": list(symbols),
        "strategy_id": strategy_id,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "params": params,
        "config": _encode_config(config),
        "user_id": user_id,
        "names": names,
    }


def _worker_entry(task: dict[str, Any], event_queue) -> None:
    """子进程入口：跑回测，把 result/error 终态消息入队。"""
    try:
        from app.runner import run_backtest, user_strategy_dirs
        from app.strategy import StrategyRegistry

        if task["kind"] != "backtest":
            raise ValueError(f"不支持的 worker 任务类型：{task['kind']}")
        reg = StrategyRegistry(user_strategy_dirs(task.get("user_id")))
        result = run_backtest(
            task["symbols"], task["strategy_id"],
            date.fromisoformat(task["start"]), date.fromisoformat(task["end"]),
            params=task.get("params"),
            config=_decode_config(task.get("config") or {}),
            registry=reg,
            benchmark=task.get("benchmark"),
            names=task.get("names"),
        )
        result.setdefault("worker", {})["pid"] = os.getpid()
        event_queue.put({"type": "result", "payload": result})
    except BaseException as exc:  # noqa: BLE001 — 子进程内任何异常都要结构化回传
        event_queue.put({
            "type": "error",
            "message": str(exc) or type(exc).__name__,
            "traceback": traceback.format_exc(),
        })
    finally:
        # 终态消息入队后显式冲刷管道（put 只是入队，写管道的是后台 feeder 线程），
        # 然后立即退出，跳过解释器 teardown（GC / 线程 join），避免撞上父进程退出预算。
        with suppress(Exception):
            event_queue.close()
            event_queue.join_thread()
        os._exit(0)


class WorkerPool:
    """spawn 子进程池：Semaphore 限并发，任务逐个在独立子进程内执行。"""

    def __init__(self, size: int = 1) -> None:
        self._size = max(1, int(size))
        # Semaphore 按事件循环惰性重建：池是模块级单例，但 asyncio.Semaphore 会绑定
        # 首个 acquire 它的 loop。CLI 的 run_backtest_offloaded 每次 asyncio.run() 新建
        # 循环，复用旧 Semaphore 会抛 "bound to a different event loop"（持锁态下必现）。
        # 记录绑定 loop，跨 loop 调用时重建，HTTP 服务单循环下零开销。
        self._sem: asyncio.Semaphore | None = None
        self._sem_loop: asyncio.AbstractEventLoop | None = None

    @property
    def size(self) -> int:
        return self._size

    def _semaphore(self) -> asyncio.Semaphore:
        loop = asyncio.get_running_loop()
        if self._sem is None or self._sem_loop is not loop:
            self._sem = asyncio.Semaphore(self._size)
            self._sem_loop = loop
        return self._sem

    async def run(
        self,
        task: dict[str, Any],
        progress_cb=None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """占用一个池位，在 spawn 子进程内跑任务并返回结果。

        子进程失败（异常/无结果退出）抛 BacktestWorkerError；timeout 触发时
        terminate 子进程并抛 asyncio.TimeoutError。主进程绝不因子进程崩溃而崩。
        """
        async with self._semaphore():
            coro = asyncio.to_thread(self._run_sync, task, progress_cb)
            if timeout is None:
                return await coro
            return await asyncio.wait_for(coro, timeout)

    def _run_sync(self, task: dict[str, Any], progress_cb) -> dict[str, Any]:
        """同步执行一个任务（在线程内调用；spawn + 队列收消息）。"""
        context = mp.get_context("spawn")
        events = context.Queue()
        process = context.Process(target=_worker_entry, args=(task, events), daemon=False)
        try:
            process.start()
        except BaseException:
            events.close()
            events.join_thread()
            raise

        result: dict[str, Any] | None = None
        failure: dict[str, Any] | None = None
        try:
            while result is None and failure is None:
                try:
                    message = events.get(timeout=0.1)
                except queue.Empty:
                    if not process.is_alive():
                        break
                    continue
                mtype = message.get("type")
                if mtype == "progress":
                    if progress_cb is not None:
                        progress_cb(message.get("payload", {}))
                elif mtype == "result":
                    result = message["payload"]
                elif mtype == "error":
                    failure = message

            # 兜底排空：子进程退出后，队列读线程可能还没把管道尾部搬进本地缓冲
            if result is None and failure is None:
                for _ in range(2):
                    try:
                        message = events.get(timeout=1.0)
                    except queue.Empty:
                        break
                    mtype = message.get("type")
                    if mtype == "result":
                        result = message["payload"]
                    elif mtype == "error":
                        failure = message

            process.join(timeout=_JOIN_TIMEOUT_SECONDS)
            terminated = process.is_alive()
            if terminated:
                # 终态消息已送达但子进程收尾慢：强制结束，不丢已送达的结果/错误
                process.terminate()
                process.join(timeout=5.0)
                logger.warning(
                    "worker 已送达终态消息但 %ds 内未退出，已强制结束（exitcode=%s）",
                    _JOIN_TIMEOUT_SECONDS, process.exitcode,
                )
            if failure is not None:
                raise BacktestWorkerError(
                    f"回测 worker 失败：{failure.get('message', '未知错误')}\n"
                    f"{failure.get('traceback', '')}".rstrip()
                )
            if result is None:
                raise BacktestWorkerError(
                    f"回测 worker 未返回结果即退出（exitcode={process.exitcode}）"
                )
            # 结果已成功送达时，exitcode 只在自然退出（0）时有意义；走了 terminate 分支
            # 的负 exitcode（-SIGTERM）会误导——结果明明正常。此时记录 None。
            result.setdefault("worker", {})["exitcode"] = (
                None if terminated else process.exitcode
            )
            return result
        finally:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5.0)
            events.close()
            events.join_thread()


def get_pool() -> WorkerPool:
    """全局池单例（大小取 QUANT_WORKER_POOL_SIZE，首次调用时创建）。"""
    global _pool
    if _pool is None:
        from app.config import settings

        _pool = WorkerPool(settings.QUANT_WORKER_POOL_SIZE)
        logger.info("回测 worker 池初始化：size=%d", _pool.size)
    return _pool


async def run_backtest_in_worker(
    symbols: list[str],
    strategy_id: str,
    start: date,
    end: date,
    params: dict | None = None,
    config=None,
    user_id: str | None = None,
    benchmark: dict | None = None,
    names: dict[str, str] | None = None,
    timeout: float | None = None,
) -> dict[str, Any]:
    """在 worker 子进程内跑回测（含基准/名称透传，避免子进程再拉一次 data-api）。"""
    task = make_backtest_task(
        symbols, strategy_id, start, end, params=params, config=config, user_id=user_id,
        names=names,
    )
    task["benchmark"] = benchmark
    return await get_pool().run(task, timeout=timeout)
