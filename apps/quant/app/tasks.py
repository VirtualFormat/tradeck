"""回测任务注册表（进程内存态，asyncio 安全），支撑任务化回测 API（进度/停止/断线重连）。

设计（对齐参照 tick-stock-panel backend/app/api/backtest.py 的任务语义，轻量化）：
- 状态机：pending → running → done / failed / cancelled（终态三选一，不可逆）。
- 每任务存最新 progress（{"day", "total", "date"}，与 minute_replay/matcher 的
  逐日回调口径一致）、终态结果/错误、创建/开始/结束时间戳。
- 断线重连由轮询天然支持：任务脱离连接独立存在，客户端掉线后重新 poll 即恢复
  最新进度/终态结果；任务不随连接断开而取消（取消必须显式调 cancel）。
- 单进程内存态（与「backend 单进程」纪律一致）；终态任务 TTL 30 分钟后清理
  （惰性清理：任意访问接口时顺手扫描，不引入后台线程）。
- 防泄漏两道闸（修复：断连不轮询不 cancel 的客户端会让 pending 任务无限堆积，
  每个任务持有全量 symbols/names/benchmark，是内存放大器）：
  ① pending+running 总量上限（MAX_ACTIVE_TASKS），超限 create 拒绝，
  API 层转 429；② pending TTL（PENDING_TTL_SECONDS），登记后迟迟未起跑
  的任务被惰性清扫标记 failed（error 注明超时取消），随后按终态 TTL 回收。
  running 不设 TTL：回测可能真的跑很久，不冤枉正常任务。
- 并发安全：poll/cancel 等同步端点由 FastAPI 放进线程池执行，与事件循环上的
  执行协程（mark_done / release）真并发（review 实测）；所有公开方法经同一把
  threading.RLock 串行化，「判断终态 + 改额度」等复合操作在同一临界区内完成。
- 任务归属（docs/MCP.md P0）：create 时登记 owner（用户 id）；poll/cancel 传入
  owner 时只认本人任务，他人任务与不存在同样抛 UnknownTaskError（API 层 404，
  不泄露任务存在性）。owner 为 None 的调用（内部/旧测试）不做归属校验。
  每用户活跃任务另有上限（max_active_per_owner），防单人占满全局额度。
- 额度按「实际仍在执行」计：cancel 让任务对客户端立即进入 cancelled 终态，但
  后台协程（协作式取消，LLM 调用/排队中的回测不会被打断）退出前额度不释放——
  执行协程须在 finally 里调 release(task_id)。否则「创建→取消」循环可绕过上限。
- 预占（reserve/release_reservation）：预拉暖缓存等长 await 前先占名额，防同一用户
  并发请求全部通过预检后白跑重活；同步回测等不登记任务的入口也经预占计入额度。
"""
from __future__ import annotations

import functools
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

# 终态任务保留时长：客户端掉线/忘关页后仍能补拉结果，超时回收内存
TASK_TTL_SECONDS = 30 * 60

# 活跃任务（pending+running）总量上限：超过即拒绝新登记（API 层转 429）。
# 取 32 的取舍：远超正常使用（单人同时挂几个回测顶天了），又足够小，
# 恶意/异常刷接口时内存占用有硬顶；终态任务不占额度（它们走 TTL 回收）。
MAX_ACTIVE_TASKS = 32

# pending 状态 TTL：登记后超过此时长仍未起跑 → 惰性清扫时标记 failed 回收。
# 场景：客户端 POST 后断连，预拉失败/后台协程未及时起跑，任务卡 pending 永不推进。
# 取 30 分钟（与终态 TTL 一致）：预拉已在登记前完成，正常任务秒级起跑，
# 30 分钟足够覆盖排队等池位的极端情况，又避免断连任务永久占位。
# running 不动：回测真实运行时长不可预估，取消只能显式发起。
PENDING_TTL_SECONDS = 30 * 60

# 终态集合（终态不可逆；cancelled 是主动取消的终态，区别于 failed）
TERMINAL_STATUSES = ("done", "failed", "cancelled")


class UnknownTaskError(KeyError):
    """任务不存在（从未创建或 TTL 已过被清理）。"""


class TaskNotRunningError(RuntimeError):
    """对终态/未启动任务执行了只允许运行中执行的操作。"""


class RegistryFullError(RuntimeError):
    """活跃任务（pending+running）已达上限，拒绝新登记（API 层转 429）。"""


class OwnerLimitError(RegistryFullError):
    """单用户活跃任务已达上限（RegistryFullError 子类：API 层同样转 429）。"""


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
    # 任务归属用户 id（None = 内部任务，不参与归属校验与单用户限额）
    owner: str | None = None
    # 是否仍占用额度：创建时 True，进入终态时置 False（运行中被取消例外，见 cancel）
    holds_slot: bool = True
    # 执行协程是否已退出（release 过）：此后任何操作都不得再让任务占位
    released: bool = False

    @property
    def terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES

    @property
    def occupying(self) -> bool:
        """是否计入活跃额度：未终态，或已终态但执行协程尚未退出（取消中）。"""
        return not self.terminal or self.holds_slot


def _locked(fn):
    """注册表公开方法加锁（RLock：内部互相调用可重入）。"""
    @functools.wraps(fn)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return fn(self, *args, **kwargs)
    return wrapper


class BacktestTaskRegistry:
    """任务注册表：create / poll / cancel / list + 终态 TTL 惰性清理。"""

    def __init__(
        self,
        ttl_seconds: float = TASK_TTL_SECONDS,
        max_active: int = MAX_ACTIVE_TASKS,
        pending_ttl_seconds: float = PENDING_TTL_SECONDS,
        max_active_per_owner: int | None = None,
    ) -> None:
        self._ttl = float(ttl_seconds)
        self._max_active = int(max_active)
        self._pending_ttl = float(pending_ttl_seconds)
        # None = 不限单用户（仅受全局上限约束）；<=0 同样视为不限
        self._max_per_owner = (
            int(max_active_per_owner) if max_active_per_owner and max_active_per_owner > 0 else None
        )
        self._lock = threading.RLock()
        self._tasks: dict[str, BacktestTask] = {}
        # 预占名额：token → owner（预拉期间 / 同步回测执行期间占位，不出现在任务列表）
        self._reservations: dict[str, str | None] = {}

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def _active_count(self, owner: str | None = None) -> int:
        """占用额度的任务数 + 预占数；owner 非空时只数该用户的。

        取消中（已终态但执行协程未退出）的任务仍计入，见模块 docstring。
        """
        tasks = sum(
            1 for t in self._tasks.values()
            if t.occupying and (owner is None or t.owner == owner)
        )
        reserved = sum(
            1 for o in self._reservations.values() if owner is None or o == owner
        )
        return tasks + reserved

    @_locked
    def has_capacity(self, owner: str | None = None) -> bool:
        """是否还能登记新任务（供 API 层在预拉暖缓存前预检，避免超限请求白跑）。"""
        try:
            self.ensure_capacity(owner)
        except RegistryFullError:
            return False
        return True

    @_locked
    def ensure_capacity(self, owner: str | None = None) -> None:
        """容量预检：全局超限抛 RegistryFullError，单用户超限抛 OwnerLimitError。"""
        self._sweep()
        if self._active_count() >= self._max_active:
            raise RegistryFullError(
                f"活跃任务已达上限 {self._max_active}（pending+running），"
                "请等待在途任务完成或显式取消后重试"
            )
        if (
            owner is not None
            and self._max_per_owner is not None
            and self._active_count(owner) >= self._max_per_owner
        ):
            raise OwnerLimitError(
                f"你的在途任务已达上限 {self._max_per_owner} 个，"
                "请等待完成或取消后重试"
            )

    @_locked
    def create(self, owner: str | None = None, reservation: str | None = None) -> BacktestTask:
        """登记一个 pending 任务（立即返回 task_id，供 API 秒回）。

        reservation：此前 reserve() 得到的预占令牌——转为正式任务（不重复计额度）。
        """
        if reservation is not None and reservation in self._reservations:
            del self._reservations[reservation]
        else:
            self.ensure_capacity(owner)
        task = BacktestTask(task_id=uuid.uuid4().hex, owner=owner)
        self._tasks[task.task_id] = task
        return task

    @_locked
    def reserve(self, owner: str | None = None) -> str:
        """预占一个名额（容量不足抛 RegistryFullError/OwnerLimitError），返回令牌。

        调用方必须 create(reservation=) 转正或 release_reservation() 归还（finally）。
        """
        self.ensure_capacity(owner)
        token = uuid.uuid4().hex
        self._reservations[token] = owner
        return token

    @_locked
    def release_reservation(self, token: str) -> None:
        """归还预占名额（幂等；已转正的令牌忽略）。"""
        self._reservations.pop(token, None)

    @_locked
    def release(self, task_id: str) -> None:
        """执行协程退出时调用（finally）：释放该任务占用的额度（幂等）。

        未终态的任务被视为异常退出，兜底标记 failed，保证额度一定归还。
        """
        task = self._tasks.get(task_id)
        if task is None:
            return
        if not task.terminal:
            self._finish(task_id, "failed", error="任务执行协程异常退出，未进入终态")
        task.holds_slot = False
        task.released = True

    @_locked
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
        # 终态默认释放额度（done/failed 由执行协程自己在退出前写入）；
        # 唯一例外是对运行中任务的 cancel，见 cancel()
        task.holds_slot = False
        return task

    @_locked
    def mark_done(self, task_id: str, result: dict[str, Any]) -> BacktestTask:
        return self._finish(task_id, "done", result=result)

    @_locked
    def mark_failed(self, task_id: str, error: str) -> BacktestTask:
        return self._finish(task_id, "failed", error=error)

    @_locked
    def mark_cancelled(self, task_id: str) -> BacktestTask:
        return self._finish(task_id, "cancelled")

    # ------------------------------------------------------------------
    # 进度 / 取消
    # ------------------------------------------------------------------

    @_locked
    def set_progress(self, task_id: str, payload: dict[str, Any]) -> None:
        """更新逐日进度（worker 线程可触发的唯一入口；仅原子赋值，无锁竞争面）。"""
        task = self._tasks.get(task_id)
        if task is None or task.terminal:
            return
        task.progress = dict(payload)

    @_locked
    def cancel(self, task_id: str, owner: str | None = None) -> BacktestTask:
        """幂等取消：终态任务返回当前状态（不报错）；运行中置取消标记并转 cancelled。

        owner 非空时只能取消本人任务（他人任务按不存在处理）。
        """
        task = self._get(task_id, owner)
        if task.terminal:
            return task  # 幂等：重复 cancel / 对已完成任务 cancel 都返回现状
        token = task.cancel_token
        if token is not None:
            token.cancel()
        started = task.started_at is not None
        self._finish(task_id, "cancelled")
        if started and not task.released:
            # 已起跑且执行协程尚未退出：协作式取消下它可能仍在跑 LLM 调用 / 等池位，
            # 额度保留到协程 finally 中 release()，防「创建→取消」循环绕过上限。
            # 与「终态判断」在同一把锁内完成，不会把已 release 的任务重新占位。
            task.holds_slot = True
        return task

    @_locked
    def attach_cancel_token(self, task_id: str, token: Any) -> None:
        """给未终态任务挂上取消令牌（后台协程起跑时调用；终态任务忽略）。"""
        task = self._tasks.get(task_id)
        if task is not None and not task.terminal:
            task.cancel_token = token

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    @_locked
    def poll(self, task_id: str, owner: str | None = None) -> dict[str, Any]:
        """轮询快照（断线重连入口）：终态附带完整结果/错误。

        owner 非空时只能查本人任务（他人任务按不存在处理）。
        """
        self._sweep()
        task = self._get(task_id, owner)
        return self.snapshot(task)

    @_locked
    def list(self, owner: str | None = None) -> list[dict[str, Any]]:
        """存活任务快照（新建在前；终态未过 TTL 的也在列）。owner 非空时只列本人任务。"""
        self._sweep()
        tasks = sorted(
            (t for t in self._tasks.values() if owner is None or t.owner == owner),
            key=lambda t: t.created_at,
            reverse=True,
        )
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

    def _get(self, task_id: str, owner: str | None = None) -> BacktestTask:
        task = self._tasks.get(task_id)
        # 归属不符与不存在同一异常：调用方无法据此探测他人任务是否存在
        if task is None or (owner is not None and task.owner != owner):
            raise UnknownTaskError(task_id)
        return task

    def _sweep(self) -> None:
        """惰性清理（访问接口时顺手做）：
        ① 终态超过 TTL 的任务从注册表移除；
        ② pending 超 TTL 仍未起跑的标记 failed（error 注明超时取消），
           转入终态 TTL 回收路径；running 不动（回测可能真的跑很久）。
        """
        now = time.time()
        # 先清扫超时 pending：转入终态后由下一轮 sweep（或本轮终态检查）回收
        for t in list(self._tasks.values()):
            if (
                t.status == "pending"
                and now - t.created_at > self._pending_ttl
            ):
                self._finish(
                    t.task_id, "failed",
                    error="任务登记后超时未启动（疑似客户端断连），已自动取消",
                )
        expired = [
            tid for tid, t in self._tasks.items()
            if t.terminal and not t.holds_slot and t.finished_at is not None
            and now - t.finished_at > self._ttl
        ]
        for tid in expired:
            self._tasks.pop(tid, None)


# 全局注册表单例（模块级；与「quant 单进程」纪律一致，进程内唯一真相源）
_registry: BacktestTaskRegistry | None = None


def get_registry() -> BacktestTaskRegistry:
    global _registry
    if _registry is None:
        from app.config import settings

        _registry = BacktestTaskRegistry(
            max_active_per_owner=settings.QUANT_MAX_CONCURRENT_PER_USER,
        )
    return _registry
