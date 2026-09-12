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


def _fake_progress_then_result(task, event_queue) -> None:
    """fake 子进程：发两条 progress 再发 result（验证跨进程消息桥接）。"""
    event_queue.put({"type": "progress", "payload": {"day": 1, "total": 2, "date": "2026-01-05"}})
    event_queue.put({"type": "progress", "payload": {"day": 2, "total": 2, "date": "2026-01-06"}})
    event_queue.put({"type": "result", "payload": {"stats": {"trades": 0}, "worker": {}}})
    event_queue.close()
    event_queue.join_thread()
    import os
    os._exit(0)


def _fake_spin(task, event_queue) -> None:
    """fake 子进程：发一条 progress 后死循环（等父进程 cancel terminate）。"""
    event_queue.put({"type": "progress", "payload": {"day": 1, "total": 999, "date": "2026-01-05"}})
    while True:  # pragma: no cover — 靠 terminate 结束
        time.sleep(0.05)


class TestWorkerBridge(unittest.TestCase):
    """WorkerPool._run_sync 的 progress 转发与 cancel terminate（线程内直接调）。"""

    def _run_sync(self, entry, progress_cb=None, cancel_token=None):
        """临时替换子进程入口后跑 _run_sync（避开真回测/spawn 重计算）。"""
        import app.worker as worker_mod

        pool = WorkerPool(size=1)
        original = worker_mod._worker_entry
        worker_mod._worker_entry = entry
        try:
            return pool._run_sync({"kind": "backtest"}, progress_cb, cancel_token)
        finally:
            worker_mod._worker_entry = original

    def test_progress_forwarded_and_result_returned(self) -> None:
        seen: list[dict] = []
        result = self._run_sync(_fake_progress_then_result, progress_cb=seen.append)
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
        result = self._run_sync(_fake_progress_then_result)
        self.assertIn("stats", result)

    def test_cancel_terminates_child(self) -> None:
        token = CancelToken()
        seen: list[dict] = []

        def cancel_soon(payload: dict) -> None:
            seen.append(payload)
            token.cancel()  # 收到首日进度即请求取消（模拟前端点停止）

        with self.assertRaises(BacktestCancelledError):
            self._run_sync(_fake_spin, progress_cb=cancel_soon, cancel_token=token)
        self.assertEqual(len(seen), 1)  # 确实跑到过子进程，再被 terminate


if __name__ == "__main__":
    unittest.main()
