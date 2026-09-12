"""result_stats 扩展统计 + stats.compute 蒙特卡洛回撤的单元测试。

覆盖：分标的聚合正确性、空输入降级、分桶边界、bootstrap 可复现性（固定种子）。
"""
from __future__ import annotations

import unittest
from datetime import date, timedelta

import numpy as np

from app.engine import stats
from app.engine.matcher import SimResult, Trade
from app.engine.result_stats import (
    daily_trade_rows, per_symbol_stats, return_distribution, selection_stats,
)


def _trade(
    symbol: str,
    entry: date,
    exit_: date,
    pnl: float,
    ret: float,
    exit_reason: str = "signal",
) -> Trade:
    return Trade(
        symbol=symbol, entry_date=entry, exit_date=exit_,
        entry_price=10.0, exit_price=10.0 * (1 + ret), shares=100.0,
        pnl=pnl, ret=ret, exit_reason=exit_reason,
    )


class PerSymbolStatsTest(unittest.TestCase):
    """分标的聚合：选股次数/复利总收益/胜率/最佳最差/总盈亏金额。"""

    def test_empty(self) -> None:
        self.assertEqual(per_symbol_stats([]), [])

    def test_aggregation_hand_calc(self) -> None:
        d0 = date(2025, 1, 6)
        trades = [
            # 600000.SH 两笔：+10% 后 -5%，复利 = 1.1*0.95-1 = 0.045
            _trade("600000.SH", d0, d0 + timedelta(days=1), 1000.0, 0.10),
            _trade("600000.SH", d0 + timedelta(days=2), d0 + timedelta(days=3), -500.0, -0.05),
            # AAPL 一笔 +20%
            _trade("AAPL", d0, d0 + timedelta(days=4), 2000.0, 0.20),
        ]
        rows = per_symbol_stats(trades)
        self.assertEqual(len(rows), 2)
        # 按总收益降序：AAPL (0.2) 在前，600000.SH (0.045) 在后
        self.assertEqual(rows[0]["symbol"], "AAPL")
        self.assertEqual(rows[0]["n_trades"], 1)
        self.assertAlmostEqual(rows[0]["total_return"], 0.2, places=4)
        self.assertEqual(rows[0]["win_rate"], 1.0)
        self.assertEqual(rows[0]["total_pnl"], 2000.0)
        sh = rows[1]
        self.assertEqual(sh["symbol"], "600000.SH")
        self.assertEqual(sh["n_trades"], 2)
        self.assertAlmostEqual(sh["total_return"], 0.045, places=4)
        self.assertEqual(sh["win_rate"], 0.5)
        self.assertAlmostEqual(sh["best"], 0.10, places=4)
        self.assertAlmostEqual(sh["worst"], -0.05, places=4)
        self.assertEqual(sh["total_pnl"], 500.0)


class ReturnDistributionTest(unittest.TestCase):
    """收益分布直方图：分桶边界 / clip / 占比和。"""

    def test_empty(self) -> None:
        self.assertEqual(return_distribution([]), [])

    def test_bin_count_and_ratio_sum(self) -> None:
        d0 = date(2025, 1, 6)
        trades = [
            _trade("A", d0, d0, 1.0, 0.0),      # 恰在 0 边界 → 第 10 桶 [0, 0.02)
            _trade("B", d0, d0, 1.0, 0.03),     # [+2%, +4%) 桶
            _trade("C", d0, d0, -1.0, -0.30),   # 超界 clip 到 -20% 最外桶
            _trade("D", d0, d0, 1.0, 0.25),     # 超界 clip 到 +20% 最外桶
        ]
        dist = return_distribution(trades, bins=20)
        self.assertEqual(len(dist), 20)
        total = sum(b["count"] for b in dist)
        self.assertEqual(total, 4)  # clip 不丢样本
        self.assertAlmostEqual(sum(b["ratio"] for b in dist), 1.0, places=4)
        # 最外两桶各 1（clip 进界），中间桶合计 2
        self.assertEqual(dist[0]["count"], 1)   # -20%~-18% 桶（-0.30 clip）
        self.assertEqual(dist[-1]["count"], 1)  # +18%~+20% 桶（+0.25 clip）
        # 0.0 落在 [0, 0.02) 桶（np.histogram 左闭右开），0.03 落在 [0.02, 0.04)
        counts_mid = sum(b["count"] for b in dist[1:-1])
        self.assertEqual(counts_mid, 2)

    def test_custom_bins(self) -> None:
        d0 = date(2025, 1, 6)
        trades = [_trade("A", d0, d0, 1.0, 0.01)] * 5
        dist = return_distribution(trades, bins=10)
        self.assertEqual(len(dist), 10)
        self.assertEqual(sum(b["count"] for b in dist), 5)


class DailyTradeRowsTest(unittest.TestCase):
    """按日聚合：买卖笔数 / 当日与累计已实现盈亏。"""

    def test_empty(self) -> None:
        self.assertEqual(daily_trade_rows([], [], []), [])

    def test_aggregation_and_cumsum(self) -> None:
        d0 = date(2025, 1, 6)
        dates = [d0 + timedelta(days=i) for i in range(4)]
        equity = [100.0, 110.0, 105.0, 120.0]
        trades = [
            _trade("A", dates[0], dates[1], 500.0, 0.05),   # 买 d0 卖 d1
            _trade("B", dates[0], dates[2], -200.0, -0.02), # 买 d0 卖 d2
            _trade("C", dates[2], dates[3], 300.0, 0.03),   # 买 d2 卖 d3
        ]
        rows = daily_trade_rows(trades, dates, equity)
        self.assertEqual(len(rows), 4)
        # d0：两笔买入，无卖出，无盈亏
        self.assertEqual((rows[0]["buys"], rows[0]["sells"], rows[0]["realized_pnl"]), (2, 0, 0.0))
        # d1：卖出一笔 +500
        self.assertEqual((rows[1]["sells"], rows[1]["realized_pnl"]), (1, 500.0))
        # d2：买入一笔 + 卖出一笔 -200，累计 500-200=300
        self.assertEqual(rows[2]["buys"], 1)
        self.assertEqual(rows[2]["realized_pnl"], -200.0)
        self.assertEqual(rows[2]["cumulative_pnl"], 300.0)
        # d3：卖出 +300，累计 600
        self.assertEqual(rows[3]["cumulative_pnl"], 600.0)
        # equity 逐日对齐透传
        self.assertEqual([r["equity"] for r in rows], equity)


class SelectionStatsTest(unittest.TestCase):
    """选择漏斗：透传可统计的计数（信号数/成交数）。"""

    def test_passthrough(self) -> None:
        s = selection_stats(12, 7, 3)
        self.assertEqual(s, {"signals_entry": 12, "signals_exit": 7, "filled_trades": 3})

    def test_zero(self) -> None:
        s = selection_stats(0, 0, 0)
        self.assertEqual(s["signals_entry"], 0)
        self.assertEqual(s["filled_trades"], 0)


class McMaxddTest(unittest.TestCase):
    """蒙特卡洛最大回撤：可复现性 / 样本不足降级 / 取值域。"""

    def test_reproducible_fixed_seed(self) -> None:
        rets = np.array([0.01, -0.02, 0.015, -0.005, 0.008, -0.012, 0.02, -0.007])
        a = stats._mc_maxdd(rets)
        b = stats._mc_maxdd(rets)
        self.assertEqual(a, b)  # 固定种子两次结果一致
        p50, p95 = a
        self.assertIsNotNone(p50)
        self.assertIsNotNone(p95)
        # 回撤分位均为非正值；p95（5 分位）不优于 p50（更负或相等）
        self.assertLessEqual(p50, 0.0)
        self.assertLessEqual(p95, p50)

    def test_insufficient_samples_returns_none(self) -> None:
        self.assertEqual(stats._mc_maxdd(np.array([0.01, -0.01])), (None, None))
        self.assertEqual(stats._mc_maxdd(np.array([])), (None, None))

    def test_compute_includes_mc_fields(self) -> None:
        d0 = date(2025, 1, 2)
        equity = [100.0, 102.0, 99.0, 101.0, 103.0, 100.0, 104.0]
        res = SimResult(
            trades=[], equity_dates=[d0 + timedelta(days=i) for i in range(len(equity))],
            equity=equity, final_value=equity[-1],
        )
        out = stats.compute(res)
        self.assertIn("mc_maxdd_p50", out)
        self.assertIn("mc_maxdd_p95", out)
        self.assertIsNotNone(out["mc_maxdd_p50"])

    def test_empty_skeleton_aligned(self) -> None:
        res = SimResult(trades=[], equity_dates=[date(2025, 1, 2)], equity=[100.0], final_value=100.0)
        out = stats.compute(res)  # 走 _empty 路径
        self.assertIsNone(out["mc_maxdd_p50"])
        self.assertIsNone(out["mc_maxdd_p95"])

    def test_compute_empty_aligned(self) -> None:
        from app.runner import compute_empty
        out = compute_empty()
        self.assertIsNone(out["mc_maxdd_p50"])
        self.assertIsNone(out["mc_maxdd_p95"])


if __name__ == "__main__":
    unittest.main()
