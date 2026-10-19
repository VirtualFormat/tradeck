"""任务化回测（进度/停止/断线重连）的单元测试。

覆盖点：
- 注册表状态机：pending → running → done/failed/cancelled（终态不可逆）。
- 终态 TTL 惰性清理（过期任务从注册表消失，poll 抛 UnknownTaskError）。
- cancel 幂等：重复 cancel / 对终态任务 cancel 不报错，返回现状。
- 轮询响应结构：pending/running 不带 result/error；done 带 result；failed 带 error。
- 取消令牌桥接：cancel() 置位 CancelToken，WorkerPool._run_sync 见到置位
  即 terminate 子进程并抛 BacktestCancelledError（用 fake 子进程任务，不跑真回测）。
- worker 池 progress 桥接：子进程 progress 消息经 Queue 转发到 progress_cb
  （fake 子进程发消息，验证父进程回调收到）。
"""
from __future__ import annotations

import time
import unittest

from app.tasks import (
    TERMINAL_STATUSES,
    BacktestTaskRegistry,
    TaskNotRunningError,
    UnknownTaskError,
)
from app.worker import (
    BacktestCancelledError,
    CancelToken,
    WorkerPool,
)


class TestRegistryStateMachine(unittest.TestCase):
    """注册表状态机与终态语义。"""

    def setUp(self) -> None:
        self.reg = BacktestTaskRegistry()

    def test_pending_to_done(self) -> None:
        t = self.reg.create()
        self.assertEqual(t.status, "pending")
        self.reg.mark_running(t.task_id)
        self.assertEqual(self.reg.poll(t.task_id)["status"], "running")
        self.reg.mark_done(t.task_id, {"stats": {"total_return": 0.1}})
        snap = self.reg.poll(t.task_id)
        self.assertEqual(snap["status"], "done")
        self.assertEqual(snap["result"]["stats"]["total_return"], 0.1)
        self.assertNotIn("error", snap)
        self.assertIsNotNone(snap["finished_at"])

    def test_failed_terminal(self) -> None:
        t = self.reg.create()
        self.reg.mark_running(t.task_id)
        self.reg.mark_failed(t.task_id, "worker 炸了")
        snap = self.reg.poll(t.task_id)
        self.assertEqual(snap["status"], "failed")
        self.assertEqual(snap["error"], "worker 炸了")
        self.assertNotIn("result", snap)

    def test_terminal_is_irreversible(self) -> None:
        """终态不可逆：done 后再 mark_failed / mark_cancelled 静默忽略。"""
        t = self.reg.create()
        self.reg.mark_running(t.task_id)
        self.reg.mark_done(t.task_id, {"ok": True})
        self.reg.mark_failed(t.task_id, "迟到的失败")
        self.reg.mark_cancelled(t.task_id)
        snap = self.reg.poll(t.task_id)
        self.assertEqual(snap["status"], "done")
        self.assertEqual(snap["result"], {"ok": True})

    def test_mark_running_twice_raises(self) -> None:
        t = self.reg.create()
        self.reg.mark_running(t.task_id)
        with self.assertRaises(TaskNotRunningError):
            self.reg.mark_running(t.task_id)

    def test_unknown_task(self) -> None:
        with self.assertRaises(UnknownTaskError):
            self.reg.poll("no-such-task")
        with self.assertRaises(UnknownTaskError):
            self.reg.cancel("no-such-task")

    def test_pending_running_snapshot_has_no_result_keys(self) -> None:
        t = self.reg.create()
        snap = self.reg.poll(t.task_id)
        self.assertEqual(
            set(snap),
            {"task_id", "status", "progress", "created_at", "started_at", "finished_at"},
        )
        self.assertIsNone(snap["progress"])

    def test_progress_update(self) -> None:
        t = self.reg.create()
        self.reg.mark_running(t.task_id)
        self.reg.set_progress(t.task_id, {"day": 3, "total": 10, "date": "2026-01-08"})
        snap = self.reg.poll(t.task_id)
        self.assertEqual(snap["progress"], {"day": 3, "total": 10, "date": "2026-01-08"})
        # 终态后进度更新静默忽略（迟到消息不改终态快照）
        self.reg.mark_done(t.task_id, {})
        self.reg.set_progress(t.task_id, {"day": 99, "total": 10, "date": "x"})
        self.assertEqual(self.reg.poll(t.task_id)["progress"]["day"], 3)

    def test_list_order_and_terminal_filter(self) -> None:
        a = self.reg.create()
        b = self.reg.create()
        snaps = self.reg.list()
        self.assertEqual([s["task_id"] for s in snaps], [b.task_id, a.task_id])  # 新在前
        statuses = {s["status"] for s in snaps}
        self.assertEqual(statuses, {"pending"})
        for status in TERMINAL_STATUSES:
            self.assertIn(status, ("done", "failed", "cancelled"))


class TestRegistryOwnership(unittest.TestCase):
    """任务归属与每用户活跃上限（docs/MCP.md P0）。"""

    def setUp(self) -> None:
        self.reg = BacktestTaskRegistry(max_active_per_owner=2)

    def test_other_owner_sees_unknown(self) -> None:
        t = self.reg.create(owner="u1")
        self.assertEqual(self.reg.poll(t.task_id, owner="u1")["status"], "pending")
        with self.assertRaises(UnknownTaskError):
            self.reg.poll(t.task_id, owner="u2")
        with self.assertRaises(UnknownTaskError):
            self.reg.cancel(t.task_id, owner="u2")
        # 他人 cancel 被拒后任务原状不变
        self.assertEqual(self.reg.poll(t.task_id, owner="u1")["status"], "pending")

    def test_owner_none_skips_check(self) -> None:
        t = self.reg.create(owner="u1")
        self.assertEqual(self.reg.poll(t.task_id)["status"], "pending")

    def test_list_filters_by_owner(self) -> None:
        a = self.reg.create(owner="u1")
        self.reg.create(owner="u2")
        self.assertEqual([s["task_id"] for s in self.reg.list(owner="u1")], [a.task_id])
        self.assertEqual(len(self.reg.list()), 2)

    def test_per_owner_limit(self) -> None:
        from app.tasks import OwnerLimitError, RegistryFullError

        first = self.reg.create(owner="u1")
        self.reg.create(owner="u1")
        self.assertFalse(self.reg.has_capacity("u1"))
        with self.assertRaises(OwnerLimitError):
            self.reg.create(owner="u1")
        # OwnerLimitError 是 RegistryFullError 子类：API 层一处 except 统一转 429
        self.assertTrue(issubclass(OwnerLimitError, RegistryFullError))
        # 其他用户不受影响
        self.assertTrue(self.reg.has_capacity("u2"))
        self.reg.create(owner="u2")
        # 终态释放额度
        self.reg.cancel(first.task_id, owner="u1")
        self.assertTrue(self.reg.has_capacity("u1"))
        self.reg.create(owner="u1")

    def test_global_limit_still_applies(self) -> None:
        from app.tasks import OwnerLimitError, RegistryFullError

        reg = BacktestTaskRegistry(max_active=2, max_active_per_owner=5)
        reg.create(owner="u1")
        reg.create(owner="u2")
        with self.assertRaises(RegistryFullError) as ctx:
            reg.create(owner="u3")
        self.assertNotIsInstance(ctx.exception, OwnerLimitError)

    def test_non_positive_limit_means_unlimited(self) -> None:
        reg = BacktestTaskRegistry(max_active_per_owner=0)
        for _ in range(5):
            reg.create(owner="u1")
        self.assertTrue(reg.has_capacity("u1"))

    def test_cancel_running_keeps_slot_until_release(self) -> None:
        """运行中任务被取消：对外立即 cancelled，额度保留到执行协程 release（防创建-取消循环）。"""
        from app.tasks import OwnerLimitError

        a = self.reg.create(owner="u1")
        b = self.reg.create(owner="u1")
        self.reg.mark_running(a.task_id)
        self.assertEqual(self.reg.cancel(a.task_id, owner="u1").status, "cancelled")
        with self.assertRaises(OwnerLimitError):
            self.reg.create(owner="u1")
        self.reg.release(a.task_id)
        self.reg.create(owner="u1")
        # 未起跑（pending）即取消：没有执行协程来 release，额度当场释放
        self.reg.cancel(b.task_id, owner="u1")
        self.reg.create(owner="u1")

    def test_release_marks_unfinished_task_failed(self) -> None:
        t = self.reg.create(owner="u1")
        self.reg.mark_running(t.task_id)
        self.reg.release(t.task_id)  # 执行协程异常退出（未写终态）
        snap = self.reg.poll(t.task_id, owner="u1")
        self.assertEqual(snap["status"], "failed")
        self.reg.release(t.task_id)  # 幂等

    def test_reservation_counts_and_converts(self) -> None:
        from app.tasks import OwnerLimitError

        r1 = self.reg.reserve("u1")
        self.reg.reserve("u1")
        with self.assertRaises(OwnerLimitError):
            self.reg.reserve("u1")
        self.assertEqual(self.reg.list(owner="u1"), [])  # 预占不出现在任务列表
        t = self.reg.create(owner="u1", reservation=r1)  # 转正不重复计额度
        self.reg.release_reservation(r1)  # 已转正：空操作
        self.assertEqual(self.reg.poll(t.task_id, owner="u1")["status"], "pending")
        with self.assertRaises(OwnerLimitError):
            self.reg.reserve("u1")
        self.assertTrue(self.reg.has_capacity("u2"))


class TestRegistryConcurrency(unittest.TestCase):
    """线程池里的 poll/cancel 与事件循环上的 mark_done/release 真并发（review F1/F2）。"""

    def test_cancel_after_release_never_reoccupies(self) -> None:
        """执行协程已 release 后再到达的 cancel 不得把任务重新占位（否则额度永久泄漏）。"""
        reg = BacktestTaskRegistry(max_active_per_owner=1)
        t = reg.create(owner="u1")
        reg.mark_running(t.task_id)
        reg.mark_done(t.task_id, {"stats": {}})
        reg.release(t.task_id)
        reg.cancel(t.task_id, owner="u1")  # 迟到的 cancel：终态幂等
        self.assertFalse(reg._tasks[t.task_id].holds_slot)
        reg.create(owner="u1")

    def test_cancel_racing_done_release_does_not_leak(self) -> None:
        import sys
        import threading as _threading

        old = sys.getswitchinterval()
        sys.setswitchinterval(1e-6)  # 放大线程交错概率
        try:
            for _ in range(300):
                reg = BacktestTaskRegistry(max_active_per_owner=1)
                t = reg.create(owner="u1")
                reg.mark_running(t.task_id)

                def _finish():
                    reg.mark_done(t.task_id, {"stats": {}})
                    reg.release(t.task_id)

                a = _threading.Thread(target=_finish)
                b = _threading.Thread(target=lambda: reg.cancel(t.task_id, owner="u1"))
                a.start(); b.start(); a.join(); b.join()
                self.assertTrue(reg.has_capacity("u1"), "额度泄漏：任务结束后仍占位")
        finally:
            sys.setswitchinterval(old)

    def test_concurrent_sweep_and_create_no_errors(self) -> None:
        import threading as _threading

        reg = BacktestTaskRegistry(ttl_seconds=0)
        errors: list[BaseException] = []

        def _churn():
            try:
                for _ in range(2000):
                    t = reg.create()
                    reg.mark_cancelled(t.task_id)
            except BaseException as e:  # noqa: BLE001
                errors.append(e)

        def _poll():
            try:
                for _ in range(2000):
                    reg.list()
            except BaseException as e:  # noqa: BLE001
                errors.append(e)

        threads = [_threading.Thread(target=f) for f in (_churn, _poll, _poll)]
        for th in threads:
            th.start()
        for th in threads:
            th.join()
        self.assertEqual(errors, [])


class TestRegistryTTL(unittest.TestCase):
    """终态 TTL 惰性清理。"""

    def test_terminal_task_expires(self) -> None:
        reg = BacktestTaskRegistry(ttl_seconds=0.05)
        t = reg.create()
        reg.mark_running(t.task_id)
        reg.mark_done(t.task_id, {})
        # 未过期仍可 poll（断线重连窗口）
        self.assertEqual(reg.poll(t.task_id)["status"], "done")
        time.sleep(0.08)
        with self.assertRaises(UnknownTaskError):
            reg.poll(t.task_id)

    def test_running_task_never_expires(self) -> None:
        reg = BacktestTaskRegistry(ttl_seconds=0.01)
        t = reg.create()
        reg.mark_running(t.task_id)
        time.sleep(0.03)
        # 运行中任务不受 TTL 影响（TTL 只收终态）
        self.assertEqual(reg.poll(t.task_id)["status"], "running")


class TestCancelSemantics(unittest.TestCase):
    """cancel 幂等与取消令牌桥接。"""

    def setUp(self) -> None:
        self.reg = BacktestTaskRegistry()

    def test_cancel_running_sets_token(self) -> None:
        t = self.reg.create()
        token = CancelToken()
        self.reg.attach_cancel_token(t.task_id, token)
        self.reg.mark_running(t.task_id)
        snap = self.reg.cancel(t.task_id)
        self.assertEqual(snap.status, "cancelled")
        self.assertTrue(token.is_set())

    def test_cancel_pending_without_token(self) -> None:
        """令牌未挂上（后台协程还没起跑）时 cancel 直接转终态，不报错。"""
        t = self.reg.create()
        snap = self.reg.cancel(t.task_id)
        self.assertEqual(snap.status, "cancelled")
        # 终态后挂令牌静默忽略（不复活任务）
        self.reg.attach_cancel_token(t.task_id, CancelToken())
        self.assertEqual(self.reg.poll(t.task_id)["status"], "cancelled")

    def test_cancel_idempotent(self) -> None:
        t = self.reg.create()
        self.reg.mark_running(t.task_id)
        first = self.reg.cancel(t.task_id)
        second = self.reg.cancel(t.task_id)  # 重复 cancel 不报错
        self.assertEqual(first.status, "cancelled")
        self.assertEqual(second.status, "cancelled")
        self.assertEqual(first.finished_at, second.finished_at)  # 不重写终态时间

    def test_cancel_done_task_returns_current(self) -> None:
        """对已 done 任务 cancel 幂等返回现状（不改成 cancelled）。"""
        t = self.reg.create()
        self.reg.mark_running(t.task_id)
        self.reg.mark_done(t.task_id, {"ok": 1})
        snap = self.reg.cancel(t.task_id)
        self.assertEqual(snap.status, "done")


# ----------------------------------------------------------------------
# worker 池桥接（fake 子进程，不跑真回测，保持测试快）
# ----------------------------------------------------------------------


class TestWorkerBridge(unittest.TestCase):
    """WorkerPool._run_sync 的 progress 转发与取消（沙箱 selftest 任务，不跑真回测）。

    沙箱子进程是真实 subprocess（JSON 行协议），selftest handler 只做固定行为，
    覆盖消息桥接 / 取消整组杀 / 子进程异常与崩溃的结构化错误。
    """

    def _run_sync(self, mode: str, progress_cb=None, cancel_token=None, timeout=None):
        pool = WorkerPool(size=1)
        return pool._run_sync(
            {"mode": mode}, progress_cb, cancel_token, kind="selftest", timeout=timeout,
        )

    def test_progress_forwarded_and_result_returned(self) -> None:
        seen: list[dict] = []
        result = self._run_sync("progress", progress_cb=seen.append)
        self.assertEqual(result["stats"]["trades"], 0)
        self.assertEqual(
            seen,
            [
                {"day": 1, "total": 2, "date": "2026-01-05"},
                {"day": 2, "total": 2, "date": "2026-01-06"},
            ],
        )

    def test_no_progress_cb_still_works(self) -> None:
        """progress_cb=None 时（旧调用口径）正常收 result，不出错。"""
        result = self._run_sync("progress")
        self.assertIn("stats", result)

    def test_cancel_terminates_child(self) -> None:
        token = CancelToken()
        seen: list[dict] = []

        def cancel_soon(payload: dict) -> None:
            seen.append(payload)
            token.cancel()  # 收到首日进度即请求取消（模拟前端点停止）

        with self.assertRaises(BacktestCancelledError):
            self._run_sync("spin", progress_cb=cancel_soon, cancel_token=token)
        self.assertEqual(len(seen), 1)  # 确实跑到过子进程，再被整组杀

    def test_child_exception_becomes_worker_error(self) -> None:
        from app.worker import BacktestWorkerError

        with self.assertRaises(BacktestWorkerError) as ctx:
            self._run_sync("error")
        self.assertIn("selftest 预期异常", str(ctx.exception))

    def test_child_crash_becomes_worker_error(self) -> None:
        from app.worker import BacktestWorkerError

        with self.assertRaises(BacktestWorkerError) as ctx:
            self._run_sync("crash")
        self.assertIn("exitcode=3", str(ctx.exception))

    def test_timeout_kills_child(self) -> None:
        started = time.monotonic()
        with self.assertRaises(TimeoutError):
            self._run_sync("spin", timeout=0.5)
        self.assertLess(time.monotonic() - started, 10)


class TestWorkerPoolAsyncBridge(unittest.TestCase):
    """经 pool.run_kind（线程桥 + 池位）的端到端语义——review 发现的挂死回归。

    旧实现异常桥接 lambda 闭包引用 except 变量（Python 会在 except 结束时删除），
    loop 回调抛 NameError、future 永不完成，池位与任务一起泄漏。
    """

    def _run(self, coro_factory, budget: float = 15.0):
        import asyncio

        async def _go():
            return await asyncio.wait_for(coro_factory(), budget)

        return asyncio.run(_go())

    def test_failures_resolve_and_release_slot(self) -> None:
        from app.worker import BacktestWorkerError

        pool = WorkerPool(size=1)
        for mode, exc in (("error", BacktestWorkerError), ("crash", BacktestWorkerError)):
            with self.subTest(mode=mode):
                with self.assertRaises(exc):
                    self._run(lambda: pool.run_kind("selftest", {"mode": mode}))
        with self.assertRaises(TimeoutError):
            self._run(lambda: pool.run_kind("selftest", {"mode": "spin"}, timeout=0.5))
        token = CancelToken()
        token.cancel()
        with self.assertRaises(BacktestCancelledError):
            self._run(lambda: pool.run_kind("selftest", {"mode": "spin"}, cancel_token=token))
        # 池位全部释放：后续任务照常完成
        out = self._run(lambda: pool.run_kind("selftest", {"mode": "progress"}))
        self.assertEqual(out["stats"]["trades"], 0)

    def test_pool_cap_holds_across_event_loops(self) -> None:
        """size=1 时，不同事件循环（HTTP loop / 优化线程 loop）的任务也必须串行。"""
        import asyncio
        import threading as _threading

        pool = WorkerPool(size=1)
        active = {"now": 0, "peak": 0}
        lock = _threading.Lock()
        original = pool._run_sync

        def _tracking(*args, **kwargs):
            with lock:
                active["now"] += 1
                active["peak"] = max(active["peak"], active["now"])
            try:
                time.sleep(0.3)
                return {"ok": True}
            finally:
                with lock:
                    active["now"] -= 1

        pool._run_sync = _tracking  # type: ignore[method-assign]
        try:
            results: list = []

            def _in_new_loop():
                results.append(asyncio.run(pool.run_kind("selftest", {})))

            threads = [_threading.Thread(target=_in_new_loop) for _ in range(3)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=10)
        finally:
            pool._run_sync = original  # type: ignore[method-assign]
        self.assertEqual(len(results), 3)
        self.assertEqual(active["peak"], 1)


if __name__ == "__main__":
    unittest.main()
