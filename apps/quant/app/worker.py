"""回测 worker 池 — 沙箱子进程隔离重计算（多用户骨架 G4，docs/QUANT-BACKTEST.md v2 §0）。

设计（参照 tick-stock-panel backend/app/backtest/worker.py 的消息协议与取消语义，轻量化）：
- 子进程由 app.sandbox 拉起（docs/MCP.md「轻量沙箱」）：干净环境 + 降权 + 禁写文件，
  崩溃/超时整组杀后主进程不受影响。原 multiprocessing spawn + Queue 已废弃——
  Queue 用 pickle 回传，被用户策略攻破的子进程可伪造消息在父进程反序列化执行。
- 消息协议：子进程 → 父进程只走 JSON 行 {"type": "progress"/"result"/"error", ...}，
  父进程不反序列化任何可执行类型（日期经标记还原）。
- 池大小 = QUANT_WORKER_POOL_SIZE（默认 1 = 串行）；asyncio.Semaphore 控制同时在跑的
  子进程数，回测同步计算推到手动线程，不阻塞事件循环。
- 主动取消（任务化回测 API）：任务化入口（api POST /api/backtest/run）传入
  CancelToken；取消语义为父进程 terminate 子进程并抛 BacktestCancelledError
  （spawn 子进程是独立解释器，进程内 cancel_event 协作式取消无法跨进程传递，
  故不做「优雅中断保留部分结果」——与参照 tick-stock-panel 的 cancel_event 不同，
  这里取消即整次回测作废）。子进程本身仍支持 cancel_event（走 run_backtest_async
  → minute_replay 的逐日检查），但任务化路径未启用：跨进程传 Event 需 Manager/
  共享对象，复杂度不抵收益（terminate 已满足停止语义）。
"""
from __future__ import annotations

import asyncio
import logging
import os
import threading
from dataclasses import asdict
from datetime import date
from typing import Any

logger = logging.getLogger(__name__)


class BacktestWorkerError(RuntimeError):
    """worker 子进程失败（异常/崩溃/超时未出结果）时抛出，调用方转成结构化错误响应。"""


class BacktestCancelledError(RuntimeError):
    """任务化回测被显式取消（父进程已 terminate 子进程）；区别于子进程自身失败。"""


class CancelToken:
    """跨线程取消令牌：任务注册表（事件循环线程）置位，worker 线程轮询消费。

    threading.Event 语义的最小封装（set/is_set），名字对齐「取消」领域语义。
    """

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    def is_set(self) -> bool:
        return self._event.is_set()


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


def _load_minute_cache(
    symbols: list[str], start: date, end: date
) -> dict[str, Any] | None:
    """子进程内读分钟K 本地缓存（纯文件读，不补拉网络）。

    返回 {symbol: DataFrame}；全空返回 None（matcher 降级日K 口径）。

    设计取舍（Wave 2 review P2-8 收口）：主进程（api.py 预拉）已把分钟K 落盘，
    这里再逐 symbol 读盘 concat 一遍——看似重复，实为刻意：
    - spawn 子进程与主进程是独立解释器，内存不共享；分钟K 要进子进程只能
      随 task dict pickle 过管道。分钟帧体量无界（分钟行数 ≈ 日K ×240，
      universe=all 全市场预拉在主进程 async 组装时就会 OOM，根本轮不到
      pickle），且多 worker 并发时同一份大数据要 pickle N 次。
    - parquet 磁盘缓存即「跨进程序列化介质」：主进程预拉只补缺口（命中时
      零网络），本函数是纯本地 parquet 读 + concat，既是快速路径也是唯一
      可行的传输通道。同步版 run_backtest_async 的内存帧透传只在同进程
      成立，跨进程不可照搬。
    结论：保持「主进程预拉落缓存 + 子进程读缓存」，不向 task dict 塞分钟帧。
    """
    from app.data.client_minute import load_minute

    out: dict[str, Any] = {}
    for symbol in symbols:
        frames = [
            df
            for year in range(start.year, end.year + 1)
            if not (df := load_minute(symbol, year)).is_empty()
        ]
        if frames:
            import polars as pl

            out[symbol] = pl.concat(frames).sort("datetime")
    return out or None


def make_backtest_task(
    symbols: list[str],
    strategy_id: str,
    start: date,
    end: date,
    params: dict | None = None,
    config=None,
    user_id: str | None = None,
    names: dict[str, str] | None = None,
    sim_mode: str = "position",
) -> dict[str, Any]:
    """打包一次回测任务（可经 Queue 传给 spawn 子进程）。

    sim_mode："position"（默认，组合模拟）/ "full"（全量模拟，候选独立执行，
    子进程内分流到 runner.run_backtest_full）。
    """
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
        "sim_mode": sim_mode,
    }


def _progress_every_for_range(start: date, end: date) -> int:
    """按区间长度取进度节流档位：目标 ≤100 条跨进程 Queue 消息。

    以自然日估算（含周末，偏保守）；matcher 末日必回调，前端进度条
    总能见到 100%。
    """
    days = max((end - start).days + 1, 1)
    return max(1, days // 100)


def execute_backtest_task(task: dict[str, Any], emit_progress) -> dict[str, Any]:
    """在沙箱子进程内执行一个回测任务（app.sandbox 的 backtest handler 调用）。

    emit_progress(payload)：逐日进度回传（父进程桥接到任务注册表）。
    """
    from app.runner import run_backtest, run_backtest_full, user_strategy_dirs
    from app.strategy import StrategyRegistry

    if task["kind"] != "backtest":
        raise ValueError(f"不支持的 worker 任务类型：{task['kind']}")
    progress_enabled = bool(task.get("progress_enabled"))
    # 全量模拟（候选独立执行）：分流到 run_backtest_full（不走 matcher.simulate；
    # 分钟K 预拉/装配对该模式无意义，跳过 minute 缓存读取）
    full_mode = task.get("sim_mode") == "full"

    # 子进程内才真正执行用户代码（sandbox=False）；user_id 用于 scoring 白名单合成
    reg = StrategyRegistry(user_strategy_dirs(task.get("user_id")), user_id=task.get("user_id"))
    config = _decode_config(task.get("config") or {})
    # 分钟口径（minute_fill / signal_next_minute）：子进程内从本地分钟缓存读
    # （load_minute 纯文件读）；缓存缺失则 matcher 无 loader 降级日K。
    # 注意：子进程不补拉网络数据（避免子进程做 IO / 与主进程缓存写竞争），
    # 分钟K 需调用方预拉（HTTP API 入口）或读历史缓存。
    # 日K 同理（冷启动修复纪律）：子进程只调同步 run_backtest/run_backtest_full
    # 读本地 Parquet 缓存，回源补拉只发生在主进程（api_backtest/api_backtest_run/
    # run_optimize 等 async 入口经 matrix.build_async 暖缓存后派发本 worker）。
    minute_bars = None
    if not full_mode and (
        config.minute_fill or config.exit_fill == "signal_next_minute"
    ):
        minute_bars = _load_minute_cache(
            task["symbols"],
            date.fromisoformat(task["start"]),
            date.fromisoformat(task["end"]),
        )
    if full_mode:
        result = run_backtest_full(
            task["symbols"], task["strategy_id"],
            date.fromisoformat(task["start"]), date.fromisoformat(task["end"]),
            params=task.get("params"),
            config=config,
            registry=reg,
            benchmark=task.get("benchmark"),
            names=task.get("names"),
            progress_cb=emit_progress if progress_enabled else None,
        )
    else:
        result = run_backtest(
            task["symbols"], task["strategy_id"],
            date.fromisoformat(task["start"]), date.fromisoformat(task["end"]),
            params=task.get("params"),
            config=config,
            registry=reg,
            benchmark=task.get("benchmark"),
            names=task.get("names"),
            minute_bars=minute_bars,
            progress_cb=emit_progress if progress_enabled else None,
            # 进度节流（P2）：按区间交易日数取档（≤100 条进度消息），
            # 长区间不再逐日回传；末日消息由 matcher 保证必发
            progress_every=_progress_every_for_range(
                date.fromisoformat(task["start"]), date.fromisoformat(task["end"])
            ),
        )
    result.setdefault("worker", {})["pid"] = os.getpid()
    return result


class WorkerPool:
    """spawn 子进程池：Semaphore 限并发，任务逐个在独立子进程内执行。"""

    def __init__(self, size: int = 1) -> None:
        self._size = max(1, int(size))
        # 进程级并发闸（跨事件循环）：优化/walk-forward 每组参数在新线程里 asyncio.run
        # 一个新 loop，旧实现按 loop 惰性重建 asyncio.Semaphore，会把池大小上限打穿、
        # 并把 HTTP loop 的信号量重置（review 确认：size=1 时峰值并发 2）。
        # 改为 threading.BoundedSemaphore，在工作线程内 acquire/release（finally 释放），
        # 与调用方用哪个 loop 无关。
        self._slots = threading.BoundedSemaphore(self._size)

    @property
    def size(self) -> int:
        return self._size

    async def run(
        self,
        task: dict[str, Any],
        progress_cb=None,
        cancel_token: CancelToken | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """占用一个池位，在沙箱子进程内跑任务并返回结果。

        子进程失败（异常/无结果退出）抛 BacktestWorkerError；timeout 触发时
        整组杀子进程并抛 TimeoutError。cancel_token 置位时整组杀子进程并抛
        BacktestCancelledError。主进程绝不因子进程崩溃而崩。

        线程桥接纪律（2026-09-13 定位的真实死结）：不能用 asyncio.to_thread /
        run_in_executor——旧 multiprocessing spawn 实现与 asyncio executor 线程组合
        曾在 Python 3.11/3.12 复现挂死。现已改沙箱 subprocess，仍保留手动
        threading.Thread + loop.call_soon_threadsafe 桥接 Future（已验证可用）。
        超时下沉到沙箱层：到点整组杀子进程（外层 wait_for 只能放弃等待，杀不掉进程）。
        """
        return await self._run_in_thread(task, progress_cb, cancel_token, timeout=timeout)

    def _run_in_thread(
        self,
        task: dict[str, Any],
        progress_cb,
        cancel_token: CancelToken | None,
        kind: str = "backtest",
        timeout: float | None = None,
    ) -> "asyncio.Future":
        """手动线程跑 _run_sync，结果经 call_soon_threadsafe 桥回当前 loop。

        替代 asyncio.to_thread（见 run() docstring 的死结说明）。池位在工作线程内
        获取：排队期间被取消的任务拿到池位后先检查令牌，不再白拉子进程。
        """
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()

        def _resolve(fn, value) -> None:
            if not future.done():
                fn(value)

        def _target() -> None:
            try:
                with self._slots:
                    if cancel_token is not None and cancel_token.is_set():
                        raise BacktestCancelledError("回测任务已被取消")
                    result = self._run_sync(
                        task, progress_cb, cancel_token, kind=kind, timeout=timeout,
                    )
            except BaseException as exc:  # noqa: BLE001 — 线程内异常桥回 loop
                # 必须经参数传递：except 块结束时 Python 会删除 exc，
                # 闭包延迟引用会在 loop 回调里抛 NameError，future 永不完成（池位/任务泄漏）
                loop.call_soon_threadsafe(_resolve, future.set_exception, exc)
            else:
                loop.call_soon_threadsafe(_resolve, future.set_result, result)

        threading.Thread(target=_target, daemon=True).start()
        return future

    def _run_sync(
        self,
        task: dict[str, Any],
        progress_cb,
        cancel_token: CancelToken | None = None,
        kind: str = "backtest",
        timeout: float | None = None,
    ) -> Any:
        """同步执行一个任务（在线程内调用；沙箱子进程 + JSON 行收消息）。

        超时抛 TimeoutError（Python 3.11+ 即 asyncio.TimeoutError，调用方口径不变）。
        """
        from app.sandbox import SandboxCancelled, SandboxError, run_sandboxed

        try:
            return run_sandboxed(
                kind, task, progress_cb=progress_cb,
                cancel_check=(cancel_token.is_set if cancel_token is not None else None),
                timeout=timeout,
            )
        except SandboxCancelled as e:
            raise BacktestCancelledError("回测任务已被取消") from e
        except SandboxError as e:
            raise BacktestWorkerError(f"回测 worker 失败：{e}") from e

    async def run_kind(
        self,
        kind: str,
        task: dict[str, Any],
        progress_cb=None,
        cancel_token: CancelToken | None = None,
        timeout: float | None = None,
    ) -> Any:
        """通用入口：占池位在沙箱子进程跑 kind 类任务（screen / trial 等）。"""
        return await self._run_in_thread(
            task, progress_cb, cancel_token, kind=kind, timeout=timeout,
        )


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
    sim_mode: str = "position",
    progress_cb=None,
    cancel_token: CancelToken | None = None,
    timeout: float | None = None,
) -> dict[str, Any]:
    """在 worker 子进程内跑回测（含基准/名称透传，避免子进程再拉一次 data-api）。

    progress_cb：逐日进度回调（跨进程桥接：子进程逐日 progress 消息经 Queue
    回父进程后调它）；为 None 时子进程不发 progress 消息（零开销，兼容旧调用）。
    cancel_token：任务化取消（父进程 terminate 子进程语义，见模块 docstring）。
    """
    task = make_backtest_task(
        symbols, strategy_id, start, end, params=params, config=config, user_id=user_id,
        names=names, sim_mode=sim_mode,
    )
    task["benchmark"] = benchmark
    task["progress_enabled"] = progress_cb is not None
    return await get_pool().run(
        task, progress_cb=progress_cb, cancel_token=cancel_token, timeout=timeout,
    )


async def run_screen_in_worker(
    strategy_id: str,
    symbols: list[str],
    end_date: date | None,
    params: dict | None,
    user_id: str | None,
    timeout: float | None = None,
) -> dict[str, Any]:
    """在沙箱子进程内跑选股（用户策略专用；builtin 由调用方进程内直跑）。

    返回 {strategy_id, as_of(date), rows[{symbol,name,score,entry,exit,market}], total, unadjusted}。
    策略存在性由调用方先用沙箱模式注册表校验（KeyError → 404），这里不再区分。
    """
    task = {
        "strategy_id": strategy_id,
        "symbols": list(symbols),
        "end_date": end_date.isoformat() if end_date else None,
        "params": params,
        "user_id": user_id,
    }
    return await get_pool().run_kind("screen", task, timeout=timeout)


# 试加载超时：合成矩阵 260×40，正常亚秒级；超时多半是策略顶层死循环
_TRIAL_TIMEOUT_SECONDS = 15.0
# 试加载全局并发闸：试加载不占 worker 池位（不应排在分钟级回测之后），
# 但必须有上限——否则并发 validate/save 会耗尽 FastAPI 线程池并无限拉起子进程
_TRIAL_MAX_CONCURRENT = 2
_trial_slots = threading.BoundedSemaphore(_TRIAL_MAX_CONCURRENT)
# 拿不到试加载名额时的最长等待（超出即视为繁忙，调用方转 429）
_TRIAL_ACQUIRE_TIMEOUT_SECONDS = 5.0


class TrialBusyError(RuntimeError):
    """试加载并发已满（调用方转 429，提示稍后重试）。"""


def trial_load_sandboxed(
    path, source: str, user_id: str | None, extra_dirs: dict | None = None,
    timeout: float = _TRIAL_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """同步：在沙箱子进程内试加载策略文件 + 合成矩阵试跑 compute（保存/校验用）。

    不占 worker 池位，由独立并发闸（_TRIAL_MAX_CONCURRENT）限流；调用方须在线程中
    调用（FastAPI 同步端点即运行在线程池）。失败抛 SandboxError / TimeoutError，
    繁忙抛 TrialBusyError；文案已截断，可直接回显。
    """
    from app.sandbox import run_sandboxed

    task = {
        "path": str(path),
        "source": source,
        "user_id": user_id,
        "extra_dirs": {k: str(v) for k, v in (extra_dirs or {}).items()},
    }
    if not _trial_slots.acquire(timeout=_TRIAL_ACQUIRE_TIMEOUT_SECONDS):
        raise TrialBusyError("策略校验繁忙，请稍后重试")
    try:
        return run_sandboxed("trial", task, timeout=timeout)
    finally:
        _trial_slots.release()
