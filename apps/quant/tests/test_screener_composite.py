"""screener/executor 对 composite 策略的截面合并口径回归测试（review 缺陷 2）。

旧实现对 composite 策略直接把 merge_signal_matrices 的持仓窗口投影 exit[last]
透传为选股页 exit 信号——投影口径下「无持仓标的的当日 exit 被吞掉」，
与子策略单独选股的 exit 语义矛盾。修复后 screen() 对 composite 改走
strategy/composite.py 的 merge_screen_results（截面口径：exit = 任一子策略
当日 exit）；非 composite 路径不变。

测试方式与 test_universe 同款：mock build / factors.load，注入桩 registry，
不触网、不读缓存。
"""
from __future__ import annotations

import unittest
from datetime import date, timedelta
from unittest import mock

import numpy as np

from app.matrix import MarketMatrix
from app.screener.executor import screen

_D0 = date(2026, 1, 5)  # 周一
_N_DAYS = 30
SYMBOLS = ["AAA", "BBB"]


def _fake_matrix(symbols: list[str]) -> MarketMatrix:
    dates = [_D0 + timedelta(days=i) for i in range(_N_DAYS)]
    shape = (_N_DAYS, len(symbols))
    close = np.full(shape, 10.0)
    return MarketMatrix(
        dates=dates, symbols=list(symbols),
        open=close.copy(), high=close.copy(), low=close.copy(), close=close,
        volume=np.full(shape, 1e6), amount=np.full(shape, 1e7),
    )


class _FakeSignals:
    """桩信号矩阵：指定 (t, asset) 格置位。"""

    def __init__(self, shape, entry_cells=(), exit_cells=(), scores=None):
        self.entry = np.zeros(shape, dtype=bool)
        self.exit = np.zeros(shape, dtype=bool)
        self.score = np.full(shape, np.nan)
        for t, a in entry_cells:
            self.entry[t, a] = True
        for t, a in exit_cells:
            self.exit[t, a] = True
        for (t, a), v in (scores or {}).items():
            self.score[t, a] = v


class _FakeCompositeStrat:
    """桩 composite 策略定义：executor 用到的字段全集。"""

    def __init__(self):
        self.meta = {"id": "combo", "limit": 100, "descending": True}
        self.is_composite = True
        self.composite_children = [("child_a", 1.0), ("child_b", 1.0)]
        self.composite_merge_mode = "union"
        self.composite_min_confirm = 0


class _FakeLeafStrat:
    def __init__(self, strategy_id: str):
        self.meta = {"id": strategy_id, "limit": 100, "descending": True}
        self.is_composite = False


class _FakeRegistry:
    """桩注册表：combo 走 composite 分支；child_a/child_b 返回各自桩信号。

    场景设计（投影口径与截面口径产生分歧的最小案例）：
    - child_a：最新交易日对 AAA 有 entry，无 exit。
    - child_b：最新交易日对 BBB 有 entry + exit；BBB 此前无 child_b entry
      （持仓窗口投影下该 exit 会被吞掉——旧实现的 bug 形态）。
    """

    def __init__(self):
        self._strat = _FakeCompositeStrat()

    def get(self, strategy_id: str):
        if strategy_id == "combo":
            return self._strat
        return _FakeLeafStrat(strategy_id)

    def run(self, strategy_id: str, enriched, params):
        shape = enriched.base.close.shape
        last = shape[0] - 1
        if strategy_id == "child_a":
            return _FakeSignals(
                shape,
                entry_cells=[(last, 0)],
                scores={(last, 0): 90.0, (last, 1): 40.0},
            )
        if strategy_id == "child_b":
            return _FakeSignals(
                shape,
                entry_cells=[(last, 1)],
                exit_cells=[(last, 1)],
                scores={(last, 0): 50.0, (last, 1): 80.0},
            )
        raise KeyError(strategy_id)


class CompositeScreenCrossSectionTest(unittest.TestCase):
    def _run(self):
        with (
            mock.patch(
                "app.screener.executor.build",
                side_effect=lambda symbols, start, end: _fake_matrix(symbols),
            ),
            mock.patch(
                "app.screener.executor.factors.load",
                side_effect=lambda s: None,  # 无因子 → 降级无复权（不影响信号口径）
            ),
        ):
            return screen("combo", symbols=SYMBOLS, registry=_FakeRegistry())

    def test_exit_row_is_cross_sectional_any_child(self) -> None:
        """BBB 当日有 child_b exit（虽持仓窗口投影会吞掉它）：截面口径须透出 exit=True。"""
        result = self._run()
        rows = {r.symbol: r for r in result.rows}
        self.assertIn("BBB", rows)
        self.assertEqual(rows["BBB"].signals["exit"], True)
        # AAA 无任一子策略 exit
        self.assertEqual(rows["AAA"].signals["exit"], False)

    def test_score_from_merge_screen_results_scale(self) -> None:
        """融合分走 merge_screen_results 的排名归一 0-100 口径，而非原始 score 透传。"""
        result = self._run()
        rows = {r.symbol: r for r in result.rows}
        # 两个子策略各命中 AAA/BBB：单候选子内中性分 0.5 → 融合 50.0
        # （等权 1:1，merge_screen_results 单候选用 _NEUTRAL_NORM=0.5）
        self.assertAlmostEqual(rows["AAA"].score, 50.0)
        self.assertAlmostEqual(rows["BBB"].score, 50.0)

    def test_entry_and_total(self) -> None:
        """union 模式下两个子策略命中的并集都入选。"""
        result = self._run()
        self.assertEqual(result.total, 2)
        self.assertEqual(sorted(r.symbol for r in result.rows), ["AAA", "BBB"])
        for r in result.rows:
            self.assertTrue(r.signals["entry"])


if __name__ == "__main__":
    unittest.main()
