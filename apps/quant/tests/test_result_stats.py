"""result_stats 扩展统计 + stats.compute 蒙特卡洛回撤的单元测试。

覆盖：分标的聚合正确性、空输入降级、分桶边界、bootstrap 可复现性（固定种子）。
"""
from __future__ import annotations

import unittest
from datetime import date, timedelta
from types import SimpleNamespace

import numpy as np

from app.engine import stats
from app.engine.matcher import SimResult, Trade
from app.engine.result_stats import (
    daily_trade_rows, factor_attribution, per_symbol_stats,
    return_distribution, selection_stats,
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

    def test_execution_stats_funnel_keys(self) -> None:
        # M2 漏斗扩展：execution_stats 有值的拦截键并入输出
        s = selection_stats(12, 7, 3, execution_stats={
            "blocked_buy_limit": 2,
            "blocked_sell_limit": 1,
            "skipped_max_positions": 4,
            "skipped_cooldown": 3,
        })
        self.assertEqual(s["blocked_buy_limit"], 2)
        self.assertEqual(s["blocked_sell_limit"], 1)
        self.assertEqual(s["skipped_max_positions"], 4)
        self.assertEqual(s["skipped_cooldown"], 3)

    def test_execution_stats_zero_and_unknown_keys_omitted(self) -> None:
        # 宁缺勿假：零值键不输出；未知键不透传（防口径漂移混入前端映射）
        s = selection_stats(1, 1, 1, execution_stats={
            "blocked_buy_limit": 0,
            "skipped_no_cash": 0,
            "some_future_key": 9,
        })
        self.assertEqual(set(s), {"signals_entry", "signals_exit", "filled_trades"})

    def test_execution_stats_default_none(self) -> None:
        # 不传 execution_stats 与旧行为一致（向后兼容）
        s = selection_stats(5, 2, 1)
        self.assertEqual(set(s), {"signals_entry", "signals_exit", "filled_trades"})


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


class FactorAttributionTest(unittest.TestCase):
    """因子归因（N1）：胜/败组入场信号日因子均值对比。

    口径：matcher 默认 open_t+1 —— T 日收盘出信号、T+1 开盘成交，
    信号日 = entry_date 的前一个矩阵交易日（索引 i-1，i=0 跳过计数）。
    """

    @staticmethod
    def _enriched(indicators: dict[str, list[list[float]]]):
        """合成最小 enriched 替身：只需 .indicators dict（行=交易日，列=标的）。"""
        return SimpleNamespace(
            indicators={k: np.array(v, dtype=float) for k, v in indicators.items()}
        )

    def test_empty_trades_skeleton(self) -> None:
        out = factor_attribution(None, [], [], [])
        self.assertEqual(
            out,
            {"factors": [], "n_win": 0, "n_lose": 0, "skipped_no_signal_day": 0,
             "signal_day_assumption": "prev_day"},
        )

    def test_win_lose_means_hand_calc(self) -> None:
        # 2 标的 × 10 个交易日；指标 rsi14 手工构造：
        # 标的 A 信号日行 = [1.0, _, 5.0, ...]，标的 B 信号日行 = [3.0, ...]
        # 胜单两笔（A@i=2 → 信号行1 = 2.0；A@i=4 → 信号行3 = 6.0），败单一笔
        # （B@i=3 → 信号行2 = 4.0）→ win_mean = 4.0，lose_mean = 4.0，diff = 0
        # 再让 A 第二笔信号日值变大验证正 diff 排序。
        days = [date(2025, 1, 6) + timedelta(days=i) for i in range(10)]
        rsi = np.array([
            [np.nan, np.nan],   # i=0 预热
            [2.0, 10.0],        # i=1
            [9.9, 4.0],         # i=2
            [8.0, 9.9],         # i=3
            [9.9, 9.9],         # i=4
            [1.0, 1.0], [1.0, 1.0], [1.0, 1.0], [1.0, 1.0], [1.0, 1.0],
        ])
        mom = np.full((10, 2), np.nan)
        mom[1, 0] = 0.1   # A 胜单信号日（i=2 交易 → 行1）
        mom[3, 0] = 0.3   # A 第二笔胜单信号日（i=4 交易 → 行3）
        mom[2, 1] = -0.2  # B 败单信号日（i=3 交易 → 行2）
        enriched = self._enriched({"rsi14": rsi.tolist(), "momentum_5d": mom.tolist()})
        symbols = ["A", "B"]
        trades = [
            _trade("A", days[2], days[5], 100.0, 0.10),    # 胜，信号行1：rsi=2.0, mom=0.1
            _trade("A", days[4], days[6], 100.0, 0.05),    # 胜，信号行3：rsi=8.0, mom=0.3
            _trade("B", days[3], days[6], -100.0, -0.05),  # 败，信号行2：rsi=4.0, mom=-0.2
        ]
        out = factor_attribution(enriched, trades, symbols, days)
        self.assertEqual(out["n_win"], 2)
        self.assertEqual(out["n_lose"], 1)
        self.assertEqual(out["skipped_no_signal_day"], 0)
        by_factor = {f["factor"]: f for f in out["factors"]}
        # rsi14：win=(2.0+8.0)/2=5.0，lose=4.0，diff=1.0
        self.assertAlmostEqual(by_factor["rsi14"]["win_mean"], 5.0)
        self.assertAlmostEqual(by_factor["rsi14"]["lose_mean"], 4.0)
        self.assertAlmostEqual(by_factor["rsi14"]["diff"], 1.0)
        # momentum_5d：win=(0.1+0.3)/2=0.2，lose=-0.2，diff=0.4
        self.assertAlmostEqual(by_factor["momentum_5d"]["win_mean"], 0.2)
        self.assertAlmostEqual(by_factor["momentum_5d"]["lose_mean"], -0.2)
        self.assertAlmostEqual(by_factor["momentum_5d"]["diff"], 0.4)
        # 按 |diff| 降序：rsi14(1.0) 在 momentum_5d(0.4) 前
        self.assertEqual(out["factors"][0]["factor"], "rsi14")
        self.assertEqual(out["factors"][1]["factor"], "momentum_5d")

    def test_first_day_trade_skipped(self) -> None:
        # entry_date 为矩阵首个交易日（i=0，无信号日行）→ 跳过并计数；
        # 全部交易被跳过时返回骨架 + 计数。
        days = [date(2025, 1, 6) + timedelta(days=i) for i in range(10)]
        rsi = np.full((10, 2), 1.0)
        enriched = self._enriched({"rsi14": rsi.tolist()})
        trades = [
            _trade("A", days[0], days[3], 100.0, 0.10),   # i=0 → 跳过
            _trade("X", days[2], days[3], 100.0, 0.10),   # 标的不在矩阵轴 → 跳过
        ]
        out = factor_attribution(enriched, trades, ["A", "B"], days)
        self.assertEqual(out["skipped_no_signal_day"], 2)
        self.assertEqual(out["n_win"], 0)
        self.assertEqual(out["n_lose"], 0)
        self.assertEqual(out["factors"], [])

    def test_all_nan_group_mean_none(self) -> None:
        # 败组在某因子上全 NaN → lose_mean / diff 为 None；None-diff 排最后。
        days = [date(2025, 1, 6) + timedelta(days=i) for i in range(10)]
        rsi = np.full((10, 2), np.nan)
        rsi[1, 0] = 7.0   # 仅胜单信号日有值
        mom = np.full((10, 2), np.nan)
        mom[1, 0] = 0.5   # 胜
        mom[2, 1] = -0.1  # 败
        enriched = self._enriched({"rsi14": rsi.tolist(), "momentum_5d": mom.tolist()})
        trades = [
            _trade("A", days[2], days[4], 100.0, 0.10),    # 胜，信号行1
            _trade("B", days[3], days[5], -100.0, -0.05),  # 败，信号行2
        ]
        out = factor_attribution(enriched, trades, ["A", "B"], days)
        by_factor = {f["factor"]: f for f in out["factors"]}
        r = by_factor["rsi14"]
        self.assertAlmostEqual(r["win_mean"], 7.0)
        self.assertIsNone(r["lose_mean"])
        self.assertIsNone(r["diff"])
        m = by_factor["momentum_5d"]
        self.assertAlmostEqual(m["win_mean"], 0.5)
        self.assertAlmostEqual(m["lose_mean"], -0.1)
        self.assertAlmostEqual(m["diff"], 0.6)
        # 有 diff 的 momentum_5d 在前，diff=None 的 rsi14 排最后
        self.assertEqual(out["factors"][0]["factor"], "momentum_5d")
        self.assertEqual(out["factors"][1]["factor"], "rsi14")

    def test_entry_date_off_axis_falls_back(self) -> None:
        # 防御口径：entry_date 不在矩阵交易日轴上（如落在周末）时向前找最近
        # 交易日作成交行，信号日取其前一行。
        days = [date(2025, 1, 6) + timedelta(days=i) for i in range(5)]  # 周一~周五
        rsi = np.full((5, 1), np.nan)
        rsi[2, 0] = 9.0   # 周三（i=2），若信号日取错会拿到这个值
        # 成交日记成周六（2025-01-11，不在轴上）→ 成交行回退到周五 i=4，信号行 i=3
        rsi[3, 0] = 6.0
        # 注意：必须先写完所有值再构造 enriched——_enriched 经 .tolist() 拷贝
        # 快照，enriched 之后再改 rsi 不会影响因子取值（初版顺序写反导致 NaN）
        enriched = self._enriched({"rsi14": rsi.tolist()})
        sat = date(2025, 1, 11)
        trades = [_trade("A", sat, sat, 100.0, 0.10)]
        out = factor_attribution(enriched, trades, ["A"], days)
        self.assertEqual(out["n_win"], 1)
        self.assertAlmostEqual(out["factors"][0]["win_mean"], 6.0)

    def test_close_t_uses_same_day(self) -> None:
        # close_t 研究口径：信号日 = 成交日当天（i 行），不是前一行
        days = [date(2025, 1, 6) + timedelta(days=i) for i in range(5)]
        rsi = np.full((5, 1), np.nan)
        rsi[2, 0] = 9.0   # 周三（i=2）= 成交日 = close_t 信号日
        rsi[1, 0] = 3.0   # 周二（i=1）= open_t+1 会取的行（应不命中）
        enriched = self._enriched({"rsi14": rsi.tolist()})
        trades = [_trade("A", days[2], days[4], 100.0, 0.10)]
        out = factor_attribution(enriched, trades, ["A"], days, entry_fill="close_t")
        self.assertEqual(out["signal_day_assumption"], "same_day")
        self.assertAlmostEqual(out["factors"][0]["win_mean"], 9.0)
        # close_t 下 i==0（成交日即首个交易日）不跳过
        trades0 = [_trade("A", days[0], days[4], 100.0, 0.10)]
        rsi[0, 0] = 5.0
        enriched0 = self._enriched({"rsi14": rsi.tolist()})
        out0 = factor_attribution(enriched0, trades0, ["A"], days, entry_fill="close_t")
        self.assertEqual(out0["skipped_no_signal_day"], 0)
        self.assertAlmostEqual(out0["factors"][0]["win_mean"], 5.0)

    def test_default_assumption_is_prev_day(self) -> None:
        # 缺省 entry_fill=open_t+1 口径标注
        out = factor_attribution(None, [], [], [])
        self.assertEqual(out["signal_day_assumption"], "prev_day")


if __name__ == "__main__":
    unittest.main()
