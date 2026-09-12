"""回测任务注册表（进程内存态，asyncio 安全），支撑任务化回测 API（进度/停止/断线重连）。

设计（对齐参照 tick-stock-panel backend/app/api/backtest.py 的任务语义，轻量化）：
- 状态机：pending → running → done / failed / cancelled（终态三选一，不可逆）。
- 每任务存最新 progress（{"day", "total", "date"}，与 minute_replay/matcher 的
  逐日回调口径一致）、终态结果/错误、创建/开始/结束时间戳。
- 断线重连由轮询天然支持：任务脱离连接独立存在，客户端掉线后重新 poll 即恢复
  最新进度/终态结果；任务不随连接断开而取消（取消必须显式调 cancel）。
- 单进程内存态（与「backend 单进程」纪律一致）；终态任务 TTL 30 分钟后清理
  （惰性清理：任意访问接口时顺手扫描，不引入后台线程）。
- 并发安全：注册表只在 quant 单进程事件循环内访问（poll/cancel 为同步函数、
  无 await 点，协程切换只发生在 await 处，天然串行）；set_progress 是唯一可能
  从 worker 线程触发的入口（见 worker 桥接说明），其自身仅做原子赋值。
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

# 终态任务保留时长：客户端掉线/忘关页后仍能补拉结果，超时回收内存
TASK_TTL_SECONDS = 30 * 60

# 终态集合（终态不可逆；cancelled 是主动取消的终态，区别于 failed）
TERMINAL_STATUSES = ("done", "failed", "cancelled")


class UnknownTaskError(KeyError):
    """任务不存在（从未创建或 TTL 已过被清理）。"""


class TaskNotRunningError(RuntimeError):
    """对终态/未启动任务执行了只允许运行中执行的操作。"""


@dataclass
class BacktestTask:
    """单个回测任务的内存态（含取消标记，由 worker 层消费）。"""

    task_id: str
    status: str = "pending"  # pending / running / done / failed / cancelled
    progress: dict[str, Any] | None = None  # 最新逐日进度 {"day","total","date"}
    result: dict[str, Any] | None = None    # done 终态的完整回测结果
    error: str | None = None                # failed 终态的结构化错误
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    # 取消请求标记（WorkerPool 持有的 CancelToken；cancel() 幂等地置位）。
    # 进程内回测协作式取消用；spawn 子进程走 terminate（见 worker.py 注释）。
    cancel_token: Any = None

    @property
    def terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES


class BacktestTaskRegistry:
    """任务注册表：create / poll / cancel / list + 终态 TTL 惰性清理。"""

    def __init__(self, ttl_seconds: float = TASK_TTL_SECONDS) -> None:
        self._ttl = float(ttl_seconds)
        self._tasks: dict[str, BacktestTask] = {}

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def create(self) -> BacktestTask:
        """登记一个 pending 任务（立即返回 task_id，供 API 秒回）。"""
        self._sweep()
        task = BacktestTask(task_id=uuid.uuid4().hex)
        self._tasks[task.task_id] = task
        return task

    def mark_running(self, task_id: str) -> BacktestTask:
        """pending → running（后台执行协程真正拿到池位/开始时调用）。"""
        task = self._get(task_id)
        if task.status != "pending":
            raise TaskNotRunningError(f"任务 {task_id} 已离开 pending 态（{task.status}）")
        task.status = "running"
        task.started_at = time.time()
        return task

    def _finish(self, task_id: str, status: str, result=None, error=None) -> BacktestTask:
        task = self._get(task_id)
        if task.terminal:
            # 终态不可逆：后台协程与 cancel 竞态时后到者静默忽略（幂等语义）
            return task
        task.status = status
        task.result = result
        task.error = error
        task.finished_at = time.time()
        return task

    def mark_done(self, task_id: str, result: dict[str, Any]) -> BacktestTask:
        return self._finish(task_id, "done", result=result)

    def mark_failed(self, task_id: str, error: str) -> BacktestTask:
        return self._finish(task_id, "failed", error=error)

    def mark_cancelled(self, task_id: str) -> BacktestTask:
        return self._finish(task_id, "cancelled")

    # ------------------------------------------------------------------
    # 进度 / 取消
    # ------------------------------------------------------------------

    def set_progress(self, task_id: str, payload: dict[str, Any]) -> None:
        """更新逐日进度（worker 线程可触发的唯一入口；仅原子赋值，无锁竞争面）。"""
        task = self._tasks.get(task_id)
        if task is None or task.terminal:
            return
        task.progress = dict(payload)

    def cancel(self, task_id: str) -> BacktestTask:
        """幂等取消：终态任务返回当前状态（不报错）；运行中置取消标记并转 cancelled。"""
        task = self._get(task_id)
        if task.terminal:
            return task  # 幂等：重复 cancel / 对已完成任务 cancel 都返回现状
        token = task.cancel_token
        if token is not None:
            token.cancel()
        return self.mark_cancelled(task_id)

    def attach_cancel_token(self, task_id: str, token: Any) -> None:
        """给未终态任务挂上取消令牌（后台协程起跑时调用；终态任务忽略）。"""
        task = self._tasks.get(task_id)
        if task is not None and not task.terminal:
            task.cancel_token = token

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    def poll(self, task_id: str) -> dict[str, Any]:
        """轮询快照（断线重连入口）：终态附带完整结果/错误。"""
        self._sweep()
        task = self._get(task_id)
        return self.snapshot(task)

    def list(self) -> list[dict[str, Any]]:
        """全部存活任务快照（新建在前；终态未过 TTL 的也在列）。"""
        self._sweep()
        tasks = sorted(self._tasks.values(), key=lambda t: t.created_at, reverse=True)
        return [self.snapshot(t) for t in tasks]

    @staticmethod
    def snapshot(task: BacktestTask) -> dict[str, Any]:
        """任务 → API 响应结构（pending/running 不带 result/error 键）。"""
        out: dict[str, Any] = {
            "task_id": task.task_id,
            "status": task.status,
            "progress": task.progress,
            "created_at": task.created_at,
            "started_at": task.started_at,
            "finished_at": task.finished_at,
        }
        if task.status == "done":
            out["result"] = task.result
        elif task.status == "failed":
            out["error"] = task.error
        return out

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _get(self, task_id: str) -> BacktestTask:
        task = self._tasks.get(task_id)
        if task is None:
            raise UnknownTaskError(task_id)
        return task

    def _sweep(self) -> None:
        """惰性 TTL 清理：终态超过 TTL 的任务从注册表移除（访问接口时顺手做）。"""
        now = time.time()
        expired = [
            tid for tid, t in self._tasks.items()
            if t.terminal and t.finished_at is not None
            and now - t.finished_at > self._ttl
        ]
        for tid in expired:
            del self._tasks[tid]


# 全局注册表单例（模块级；与「quant 单进程」纪律一致，进程内唯一真相源）
_registry: BacktestTaskRegistry | None = None


def get_registry() -> BacktestTaskRegistry:
    global _registry
    if _registry is None:
        _registry = BacktestTaskRegistry()
    return _registry
