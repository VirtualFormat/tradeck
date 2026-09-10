"""strategy.composite 叠加策略合并器的回归测试（阶段 K4 验收点固化）。

覆盖点（plans/TASKS-QUANT-BACKTEST.md K4 任务卡 + composite.py 口径注释）：
- exit 来源投影防幽灵平仓：子策略 B 的 exit 只在 B 自己 entry 后的持仓窗口内生效，
  不串平 A 的仓位（撮合引擎读全局 exit 不区分来源，投影在合并器解决）。
- entry 合并：union=OR(entries)；intersect=Σ(entries) >= min_confirm。
- 8 子策略上限：超限降级为空信号（兜底，loader 应已拦截）。
- score 融合：排名归一 [0,1] 加权、单候选中性分 50。
"""
from __future__ import annotations

import unittest

import numpy as np

from app.strategy.base import StrategySignals
from app.strategy.composite import (
    CompositeChildResult,
    merge_screen_results,
    merge_signal_matrices,
)

SHAPE = (5, 2)  # 5 个交易日 × 2 只标的


def _sig(entry_cells: list[tuple[int, int]], exit_cells: list[tuple[int, int]]) -> StrategySignals:
    entry = np.zeros(SHAPE, dtype=bool)
    exit_ = np.zeros(SHAPE, dtype=bool)
    for t, a in entry_cells:
        entry[t, a] = True
    for t, a in exit_cells:
        exit_[t, a] = True
    return StrategySignals(entry=entry, exit=exit_, score=np.full(SHAPE, np.nan))


class ExitProjectionTest(unittest.TestCase):
    """exit 来源投影：每个子策略的 exit 只在自己持仓窗口内生效。"""

    def test_no_ghost_exit(self) -> None:
        # A 在 t=1 买入标的 0；B 在 t=3 买入标的 1，t=4 对标的 0 发出 exit。
        # B 的 exit 对标的 0（B 从未 entry 过）不得投影 → 合并 exit[t=4, 标的0] = False
        sig_a = _sig(entry_cells=[(1, 0)], exit_cells=[])
        sig_b = _sig(entry_cells=[(3, 1)], exit_cells=[(4, 0)])
        merged = merge_signal_matrices(
            [sig_a, sig_b],
            children_weights=[1.0, 1.0],
            merge_mode="union",
            min_confirm=0,
            max_hold=0,  # 不封顶
            shape=SHAPE,
        )
        self.assertFalse(merged.exit[4, 0], "B 的 exit 不得平掉 A 的仓位（幽灵平仓）")

    def test_exit_projected_within_own_holding_window(self) -> None:
        # A 在 t=1 买入标的 0，t=4 自己发出 exit → 投影生效
        sig_a = _sig(entry_cells=[(1, 0)], exit_cells=[(4, 0)])
        sig_b = _sig(entry_cells=[(3, 1)], exit_cells=[])
        merged = merge_signal_matrices(
            [sig_a, sig_b],
            children_weights=[1.0, 1.0],
            merge_mode="union",
            min_confirm=0,
            max_hold=0,
            shape=SHAPE,
        )
        self.assertTrue(merged.exit[4, 0])

    def test_exit_clipped_by_max_hold_window(self) -> None:
        # A 在 t=0 买入标的 0，t=4 发出 exit；max_hold=2 → 持仓窗口 t∈[0,1]，
        # t=4 已出窗 → exit 不投影（由 max_hold 强平接管）
        sig_a = _sig(entry_cells=[(0, 0)], exit_cells=[(4, 0)])
        sig_b = _sig(entry_cells=[(3, 1)], exit_cells=[])
        merged = merge_signal_matrices(
            [sig_a, sig_b],
            children_weights=[1.0, 1.0],
            merge_mode="union",
            min_confirm=0,
            max_hold=2,
            shape=SHAPE,
        )
        self.assertFalse(merged.exit[4, 0], "max_hold 窗口外的 exit 不得投影")


class MergeModeTest(unittest.TestCase):
    """entry 合并：union / intersect（min_confirm）。"""

    def test_union_or(self) -> None:
        sig_a = _sig(entry_cells=[(1, 0)], exit_cells=[])
        sig_b = _sig(entry_cells=[(2, 1)], exit_cells=[])
        merged = merge_signal_matrices(
            [sig_a, sig_b], [1.0, 1.0], "union", 0, 0, SHAPE
        )
        self.assertTrue(merged.entry[1, 0])
        self.assertTrue(merged.entry[2, 1])

    def test_intersect_requires_min_confirm(self) -> None:
        # 标的 0：只有 A 命中（1/2 < 2）→ 不入选；标的 1：A、B 同日都命中 → 入选
        sig_a = _sig(entry_cells=[(1, 0), (1, 1)], exit_cells=[])
        sig_b = _sig(entry_cells=[(2, 0), (1, 1)], exit_cells=[])
        merged = merge_signal_matrices(
            [sig_a, sig_b], [1.0, 1.0], "intersect", 2, 0, SHAPE
        )
        self.assertFalse(merged.entry[1, 0])
        self.assertFalse(merged.entry[2, 0])
        self.assertTrue(merged.entry[1, 1])

    def test_intersect_min_confirm_one_degrades_to_union(self) -> None:
        sig_a = _sig(entry_cells=[(1, 0)], exit_cells=[])
        sig_b = _sig(entry_cells=[(2, 1)], exit_cells=[])
        merged = merge_signal_matrices(
            [sig_a, sig_b], [1.0, 1.0], "intersect", 1, 0, SHAPE
        )
        self.assertTrue(merged.entry[1, 0])
        self.assertTrue(merged.entry[2, 1])

    def test_max_children_limit_degrades_to_empty(self) -> None:
        # 9 个子策略 > MAX_COMPOSITE_CHILDREN(8) → 兜底空信号（不崩调用方）
        sigs = [_sig(entry_cells=[(1, 0)], exit_cells=[]) for _ in range(9)]
        merged = merge_signal_matrices(
            sigs, [1.0] * 9, "union", 0, 0, SHAPE
        )
        self.assertFalse(merged.entry.any())
        self.assertFalse(merged.exit.any())
        self.assertTrue(np.isnan(merged.score).all())


class ScreenMergeTest(unittest.TestCase):
    """选股合并：union / intersect / 排名归一加权。"""

    def test_union_screen(self) -> None:
        out = merge_screen_results(
            [
                CompositeChildResult(symbols={"AAA"}, scores={"AAA": 90.0}),
                CompositeChildResult(symbols={"BBB"}, scores={"BBB": 80.0}),
            ],
            children_weights=[1.0, 1.0],
            merge_mode="union",
            min_confirm=0,
        )
        self.assertEqual(set(out), {"AAA", "BBB"})

    def test_intersect_screen(self) -> None:
        out = merge_screen_results(
            [
                CompositeChildResult(symbols={"AAA", "CCC"}, scores={"AAA": 90.0, "CCC": 10.0}),
                CompositeChildResult(symbols={"BBB", "CCC"}, scores={"BBB": 80.0, "CCC": 20.0}),
            ],
            children_weights=[1.0, 1.0],
            merge_mode="intersect",
            min_confirm=2,
        )
        self.assertEqual(set(out), {"CCC"})

    def test_single_candidate_neutral_score(self) -> None:
        # 单候选无法排名 → 中性分 50（与回测合并口径一致，不凭空抬成 100）
        out = merge_screen_results(
            [CompositeChildResult(symbols={"AAA"}, scores={"AAA": 99.0})],
            children_weights=[1.0],
            merge_mode="union",
            min_confirm=0,
        )
        self.assertAlmostEqual(out["AAA"], 50.0, places=4)


if __name__ == "__main__":
    unittest.main()
