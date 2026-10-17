"""任务注册表防泄漏（容量上限 / pending TTL）的单元测试。

覆盖点（对齐 P1 缺陷修复：断连任务泄漏）：
- 上限拒绝：pending+running 达 MAX_ACTIVE_TASKS 后 create 抛 RegistryFullError；
  终态任务不占额度（done/failed/cancelled 后可继续登记）。
- has_capacity 预检：满时 False，留出额度后 True（API 层预拉前预检用）。
- pending 超时：创建超 PENDING_TTL_SECONDS 仍未 running 的任务被 _sweep 惰性
  标记 failed（error 注明超时取消），随后按终态 TTL 回收；running 不受影响。
- 终态 TTL 回收不回归：超 TTL 的终态任务被移除，poll 抛 UnknownTaskError；
  未过 TTL 的终态任务仍可 poll（客户端补拉结果窗口）。

只依赖 tasks.py 纯进程内注册表（无 polars/网络等重依赖），全程 unittest 直跑。
"""
from __future__ import annotations

import unittest

from app.tasks import (
    MAX_ACTIVE_TASKS,
    PENDING_TTL_SECONDS,
    BacktestTaskRegistry,
    RegistryFullError,
    UnknownTaskError,
)


class TestCapacityLimit(unittest.TestCase):
    """pending+running 总量上限：超限拒绝登记。"""

    def test_create_rejects_when_full(self) -> None:
        reg = BacktestTaskRegistry(max_active=3)
        tasks = [reg.create() for _ in range(3)]
        self.assertTrue(all(t.status == "pending" for t in tasks))
        with self.assertRaises(RegistryFullError):
            reg.create()

    def test_running_counts_toward_limit(self) -> None:
        reg = BacktestTaskRegistry(max_active=2)
        t1 = reg.create()
        reg.mark_running(t1.task_id)
        reg.create()
        with self.assertRaises(RegistryFullError):
            reg.create()

    def test_terminal_tasks_free_capacity(self) -> None:
        """终态（done/failed/cancelled）不占额度，可继续登记。"""
        reg = BacktestTaskRegistry(max_active=2)
        t1, t2 = reg.create(), reg.create()
        reg.mark_done(t1.task_id, {"ok": True})
        reg.mark_failed(t2.task_id, "boom")
        t3 = reg.create()  # 两个终态不占额度，应成功
        self.assertEqual(t3.status, "pending")
        # t3 占一个活跃位，再登记一个后应满
        reg.create()
        with self.assertRaises(RegistryFullError):
            reg.create()

    def test_cancelled_frees_capacity(self) -> None:
        reg = BacktestTaskRegistry(max_active=1)
        t1 = reg.create()
        reg.cancel(t1.task_id)
        reg.create()  # cancelled 不占额度

    def test_has_capacity_preflight(self) -> None:
        """API 层预检口径：满时 False；终态释放后 True。"""
        reg = BacktestTaskRegistry(max_active=1)
        self.assertTrue(reg.has_capacity())
        t = reg.create()
        self.assertFalse(reg.has_capacity())
        reg.mark_done(t.task_id, {"ok": True})
        self.assertTrue(reg.has_capacity())

    def test_default_limit_constant(self) -> None:
        """默认上限取模块常量（32）：构造不传参时生效。"""
        reg = BacktestTaskRegistry()
        for _ in range(MAX_ACTIVE_TASKS):
            reg.create()
        with self.assertRaises(RegistryFullError):
            reg.create()


class TestPendingTTL(unittest.TestCase):
    """pending 超 TTL 惰性转 failed，进入终态 TTL 回收路径。"""

    def _make_reg(self) -> BacktestTaskRegistry:
        return BacktestTaskRegistry(pending_ttl_seconds=10.0)

    def test_stale_pending_marked_failed(self) -> None:
        reg = self._make_reg()
        t = reg.create()
        t.created_at -= 11.0  # 伪造为 11s 前创建（超 10s TTL）
        snap = reg.poll(t.task_id)  # poll 触发惰性 sweep
        self.assertEqual(snap["status"], "failed")
        self.assertIn("超时", snap["error"])

    def test_fresh_pending_untouched(self) -> None:
        reg = self._make_reg()
        t = reg.create()
        snap = reg.poll(t.task_id)
        self.assertEqual(snap["status"], "pending")

    def test_running_not_swept_by_pending_ttl(self) -> None:
        """running 不设 TTL：回测可能真的跑很久，不被误杀。"""
        reg = self._make_reg()
        t = reg.create()
        t.created_at -= 3600.0  # 即使创建于 1 小时前
        reg.mark_running(t.task_id)
        snap = reg.poll(t.task_id)
        self.assertEqual(snap["status"], "running")

    def test_stale_pending_enters_terminal_ttl_path(self) -> None:
        """超时 pending 转 failed 后，再过终态 TTL 即被移除。"""
        reg = BacktestTaskRegistry(ttl_seconds=10.0, pending_ttl_seconds=5.0)
        t = reg.create()
        t.created_at -= 6.0  # 超 pending TTL
        self.assertEqual(reg.poll(t.task_id)["status"], "failed")
        t.finished_at -= 11.0  # 伪造终态已超 TTL
        with self.assertRaises(UnknownTaskError):
            reg.poll(t.task_id)

    def test_stale_pending_frees_capacity(self) -> None:
        """超时 pending 转 failed 后不占活跃额度，可登记新任务。"""
        reg = BacktestTaskRegistry(max_active=1, pending_ttl_seconds=5.0)
        t = reg.create()
        t.created_at -= 6.0
        # create 内部先 sweep，超时 pending 转 failed 释放额度
        t2 = reg.create()
        self.assertEqual(t2.status, "pending")


class TestTerminalTTLRegression(unittest.TestCase):
    """终态 TTL 回收语义不回归（修复前已有行为）。"""

    def test_terminal_removed_after_ttl(self) -> None:
        reg = BacktestTaskRegistry(ttl_seconds=10.0)
        t = reg.create()
        reg.mark_done(t.task_id, {"ok": True})
        t.finished_at -= 11.0
        with self.assertRaises(UnknownTaskError):
            reg.poll(t.task_id)

    def test_terminal_kept_within_ttl(self) -> None:
        """TTL 窗口内终态任务仍可 poll（客户端断线重连补拉结果）。"""
        reg = BacktestTaskRegistry(ttl_seconds=10.0)
        t = reg.create()
        reg.mark_done(t.task_id, {"ok": True})
        t.finished_at -= 5.0
        snap = reg.poll(t.task_id)
        self.assertEqual(snap["status"], "done")
        self.assertEqual(snap["result"], {"ok": True})

    def test_cancel_semantics_unchanged(self) -> None:
        """cancel 幂等不回归：终态任务 cancel 返回现状不报错。"""
        reg = BacktestTaskRegistry()
        t = reg.create()
        reg.mark_done(t.task_id, {"ok": True})
        snap = reg.cancel(t.task_id)
        self.assertEqual(snap.status, "done")


if __name__ == "__main__":
    unittest.main()
