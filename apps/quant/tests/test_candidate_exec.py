"""engine.candidate_exec 的回归测试（全量模拟：候选独立执行 + 样本统计口径）。

覆盖点（全部合成矩阵手算对拍，不依赖真实 data-api/网络）：
- 独立执行：3 个买入信号不受 max_positions 限制全部开仓（config.max_positions=1
  也照样 3 个），各按风控/信号退出，逐笔 pnl 与样本收益曲线手算对拍。
- 一字涨停拒买 / 一字跌停置 pending_exit 次日开盘强平（CN 标的）。
- 成本计入：佣金/印花税/滑点覆盖影响 pnl_pct（美股标的覆盖成本后手算）。
- 空信号骨架：n_candidates=0，不崩、stats 键齐全。
- stats 口径黄金断言：avg_return/median/win_rate/profit_factor/total_return/
  max_drawdown 手算对拍。
- API 层 sim_mode="full" 路由分流：worker 任务 dict 透传 + _worker_entry 分流
  到 run_backtest_full（mock 掉，不跑真回测）。
"""
from __future__ import annotations

import unittest
from datetime import date, timedelta
from unittest import mock

import numpy as np

from app.engine.candidate_exec import _candidate_stats, simulate_independent
from app.engine.matcher import MatcherConfig, Trade
from app.matrix import MarketMatrix

D0 = date(2026, 1, 5)

# US 市场零成本（commission/stamp=0，仅滑点 50bps）的滑点率
_US_SLIP = 0.005


def _dates(n: int) -> list[date]:
    return [D0 + timedelta(days=i) for i in range(n)]


def _matrix_us(
    symbols: list[str],
    opens: list,
    closes: list,
    highs: list | None = None,
    lows: list | None = None,
) -> MarketMatrix:
    """多列合成矩阵（美股标的，行=交易日、列=标的；US 零佣金零印花税）。"""
    n = len(closes)
    close = np.array(closes, dtype=np.float64)
    openp = np.array(opens, dtype=np.float64)
    high = (np.array(highs, dtype=np.float64)
            if highs is not None else np.maximum(openp, close))
    low = (np.array(lows, dtype=np.float64)
           if lows is not None else np.minimum(openp, close))
    return MarketMatrix(
        dates=_dates(n),
        symbols=symbols,
        open=openp,
        high=high,
        low=low,
        close=close,
        volume=np.full((n, len(symbols)), 1e6),
        amount=close * 1e6,
    )


def _signals(n: int, fire_days: list[int]) -> np.ndarray:
    sig = np.zeros(n, dtype=bool)
    for i in fire_days:
        sig[i] = True
    return sig


def _us_ret(entry: float, exit: float) -> float:
    """美股 100 股样本净收益率（零佣金零印花税，双边滑点 50bps）。"""
    buy_cost = entry * 100 * _US_SLIP
    sell_cost = exit * 100 * _US_SLIP
    pnl = (exit - entry) * 100 - buy_cost - sell_cost
    return pnl / (entry * 100)


class IndependentExecutionTest(unittest.TestCase):
    """3 个买入信号独立执行（max_positions=1 也全部开仓），逐笔手算对拍。"""

    def test_three_candidates_all_open_regardless_of_max_positions(self) -> None:
        # 矩阵（行=日，列=[AAA, BBB]，全美股；开盘恒平，走势全在收盘上）：
        # 信号（收盘产生，open_t+1 口径）：
        # AAA entry@0 → i=1 开盘 10 买入；exit@1 → i=2 开盘 10 卖出（signal）
        # AAA entry@1 → i=2 开盘 10 买入（与上一笔同日退出同日再开，独立样本互不
        #   挤压）；无 exit，期末 i=5 收盘 12 强平（end）
        # BBB entry@0 → i=1 开盘 20 买入；无 exit；stop_loss=-0.05：
        #   i=2 收盘 19（-5%）触发 → 按 exit_fill 口径 i=2 开盘 20 卖出（stop_loss）
        opens = [
            [10.0, 20.0],
            [10.0, 20.0],
            [10.0, 20.0],
            [10.0, 20.0],
            [10.0, 20.0],
            [10.0, 20.0],
        ]
        closes = [
            [10.0, 20.0],
            [10.0, 20.0],
            [11.0, 19.0],
            [12.0, 20.0],
            [12.0, 20.0],
            [12.0, 20.0],
        ]
        m = _matrix_us(["AAA", "BBB"], opens, closes)
        r = simulate_independent(
            m,
            entries={"AAA": _signals(6, [0, 1]), "BBB": _signals(6, [0])},
            exits={"AAA": _signals(6, [1]), "BBB": _signals(6, [])},
            # max_positions=1 也照样 3 个都开（独立执行不看仓位上限/资金池）
            config=MatcherConfig(max_positions=1, initial_capital=1.0,
                                 stop_loss_pct=-0.05),
        )
        self.assertEqual(r.n_candidates, 3)
        self.assertEqual(len(r.trades), 3)
        by_key = {(t.symbol, t.entry_date): t for t in r.trades}
        d = _dates(6)
        # ① AAA signal 退出：10 → 10
        t1 = by_key[("AAA", d[1])]
        self.assertEqual(t1.exit_date, d[2])
        self.assertEqual(t1.exit_reason, "signal")
        self.assertAlmostEqual(t1.ret, _us_ret(10.0, 10.0), places=12)
        # ② BBB 止损：20 → 20（i=2 收盘 19 触发 -5%，按 exit_fill 当日开盘 20 成交）
        t2 = by_key[("BBB", d[1])]
        self.assertEqual(t2.exit_date, d[2])
        self.assertEqual(t2.exit_reason, "stop_loss")
        self.assertAlmostEqual(t2.ret, _us_ret(20.0, 20.0), places=12)
        # ③ AAA 第二笔期末强平：10 → 12（entry_date 同为 d[2]，与 t1 退出同日）
        t3 = by_key[("AAA", d[2])]
        self.assertEqual(t3.exit_price, 12.0)  # 强平用末日收盘价（不看 exit_fill）
        self.assertEqual(t3.exit_date, d[5])
        self.assertEqual(t3.exit_reason, "end")
        self.assertAlmostEqual(t3.ret, _us_ret(10.0, 12.0), places=12)
        # 每笔固定 100 股
        for t in r.trades:
            self.assertEqual(t.shares, 100.0)
        # 样本收益曲线：d[2] 退出 2 笔平均 (r1+r2)/2，d[5] 退出 1 笔 r3（日复利）
        r1, r2, r3 = _us_ret(10.0, 10.0), _us_ret(20.0, 20.0), _us_ret(10.0, 12.0)
        self.assertEqual(r.sample_dates, [d[2], d[5]])
        e1 = 1.0 + (r1 + r2) / 2.0
        e2 = e1 * (1.0 + r3)
        self.assertAlmostEqual(r.sample_equity[0], e1, places=12)
        self.assertAlmostEqual(r.sample_equity[1], e2, places=12)
        # 期末强平不计任何执行拦截
        self.assertEqual(r.execution_stats.get("buy_no_next_bar", 0), 0)

    def test_max_hold_exit(self) -> None:
        # max_hold_days=2：i=1 买入（entry@0），k=3 时 k-i=2 ≥ 2 触发 max_hold
        m = _matrix_us(["AAA"], [[10.0]] * 5, [[10.0]] * 5)
        r = simulate_independent(
            m,
            entries={"AAA": _signals(5, [0])},
            exits={"AAA": _signals(5, [])},
            config=MatcherConfig(max_hold_days=2),
        )
        self.assertEqual(len(r.trades), 1)
        t = r.trades[0]
        self.assertEqual(t.exit_reason, "max_hold")
        self.assertEqual(t.exit_date, _dates(5)[3])


class LimitBlockTest(unittest.TestCase):
    """CN 一字涨停拒买 / 一字跌停 pending_exit 次日强平。"""

    def _cn_matrix(self, opens, closes, highs=None, lows=None,
                   vol=1e6) -> MarketMatrix:
        n = len(closes)
        close = np.array(closes, dtype=np.float64).reshape(n, 1)
        openp = np.array(opens, dtype=np.float64).reshape(n, 1)
        high = (np.array(highs, dtype=np.float64).reshape(n, 1)
                if highs is not None else np.maximum(openp, close))
        low = (np.array(lows, dtype=np.float64).reshape(n, 1)
               if lows is not None else np.minimum(openp, close))
        return MarketMatrix(
            dates=_dates(n), symbols=["600000.SH"],
            open=openp, high=high, low=low, close=close,
            volume=np.full((n, 1), vol), amount=close * max(vol, 1.0),
        )

    def test_buy_blocked_by_one_price_limit_up(self) -> None:
        # i=0 收盘 10.0；i=1 一字涨停 11.0（OHLC 全 11，=10×1.1 顶死主板涨停）
        m = self._cn_matrix(
            opens=[10.0, 11.0, 11.0],
            closes=[10.0, 11.0, 11.0],
            highs=[10.0, 11.0, 11.0],
            lows=[10.0, 11.0, 11.0],
        )
        r = simulate_independent(
            m,
            entries={"600000.SH": _signals(3, [0])},
            exits={"600000.SH": _signals(3, [])},
            config=MatcherConfig(),
        )
        self.assertEqual(r.n_candidates, 1)
        self.assertEqual(len(r.trades), 0)
        self.assertEqual(r.execution_stats.get("buy_limit_up"), 1)

    def test_sell_blocked_then_pending_exit_next_open(self) -> None:
        # i=0 收盘 10.0；entry@0 → i=1 开盘 10 买入。
        # exit@1 → i=2 触发卖出，但 i=2 一字跌停 9.0（OHLC 全 9.0）→
        # 卖出拦截、置 pending_exit；i=3 恢复正常 → 以开盘价 9.5 强平。
        m = self._cn_matrix(
            opens=[10.0, 10.0, 9.0, 9.5],
            closes=[10.0, 10.0, 9.0, 9.6],
            highs=[10.0, 10.0, 9.0, 9.6],
            lows=[10.0, 10.0, 9.0, 9.5],
        )
        r = simulate_independent(
            m,
            entries={"600000.SH": _signals(4, [0])},
            exits={"600000.SH": _signals(4, [1])},
            config=MatcherConfig(),
        )
        self.assertEqual(len(r.trades), 1)
        t = r.trades[0]
        self.assertEqual(t.exit_date, _dates(4)[3])
        self.assertEqual(t.exit_reason, "signal")  # 归因保留挂单时的原始原因
        self.assertEqual(t.exit_price, 9.5)  # 次日开盘价强平
        self.assertEqual(r.execution_stats.get("sell_limit_down"), 1)
        self.assertEqual(r.execution_stats.get("pending_exit"), 1)

    def test_non_one_price_day_is_tradable(self) -> None:
        # 收盘顶涨停但盘中开过板（非一字）→ 可成交（日K 无法判盘中开合，保守放行）
        m = self._cn_matrix(
            opens=[10.0, 10.5, 11.0],
            closes=[10.0, 11.0, 11.0],
            highs=[10.0, 11.0, 11.0],
            lows=[10.0, 10.2, 11.0],
        )
        r = simulate_independent(
            m,
            entries={"600000.SH": _signals(3, [0])},
            exits={"600000.SH": _signals(3, [])},
            config=MatcherConfig(),
        )
        self.assertEqual(len(r.trades), 1)
        self.assertIsNone(r.execution_stats.get("buy_limit_up"))


class CostTest(unittest.TestCase):
    """成本覆盖（佣金/印花税/滑点）计入 pnl。"""

    def test_cost_overrides_affect_pnl(self) -> None:
        # 美股标的 + 成本覆盖：commission=1%、印花税 0.1%、滑点 0
        # entry 10 → exit 10（平价进出）：buy=1000×0.01=10；sell=1000×(0.01+0.001)=11
        opens = [[10.0]] * 4
        closes = [[10.0], [10.0], [11.0], [11.0]]
        m = _matrix_us(["AAA"], opens, closes)
        r = simulate_independent(
            m,
            entries={"AAA": _signals(4, [0])},
            exits={"AAA": _signals(4, [1])},  # i=2 开盘 10 卖出
            config=MatcherConfig(commission_pct=0.01, stamp_tax_pct=0.001,
                                 slippage_bps=0.0),
        )
        self.assertEqual(len(r.trades), 1)
        t = r.trades[0]
        entry_cost = 10.0 * 100 * 0.01
        sell_cost = 10.0 * 100 * (0.01 + 0.001)
        pnl = 0.0 - entry_cost - sell_cost
        self.assertAlmostEqual(t.pnl, pnl, places=9)
        self.assertAlmostEqual(t.ret, pnl / 1000.0, places=12)
        self.assertLess(t.ret, 0.0)  # 平价进出因成本为负

    def test_default_us_cost_is_slippage_only(self) -> None:
        # 无卖出信号持仓到底：期末按末日收盘价 11 强平（exit_fill 不适用）
        m = _matrix_us(["AAA"], [[10.0]] * 3, [[10.0], [10.5], [11.0]])
        r = simulate_independent(
            m,
            entries={"AAA": _signals(3, [0])},
            exits={"AAA": _signals(3, [])},
            config=MatcherConfig(),
        )
        # 期末强平 exit=11：ret = (1100-1000-5-5.5)/1000
        self.assertEqual(r.trades[0].exit_reason, "end")
        self.assertEqual(r.trades[0].exit_price, 11.0)
        self.assertAlmostEqual(r.trades[0].ret, _us_ret(10.0, 11.0), places=12)


class EmptySignalTest(unittest.TestCase):
    """空信号骨架：n_candidates=0，不崩且 stats 键齐全。"""

    def test_no_signals(self) -> None:
        m = _matrix_us(["AAA"], [[10.0]] * 3, [[10.0]] * 3)
        r = simulate_independent(
            m, entries={"AAA": _signals(3, [])}, exits={"AAA": _signals(3, [])},
            config=MatcherConfig(),
        )
        self.assertEqual(r.n_candidates, 0)
        self.assertEqual(r.trades, [])
        self.assertEqual(r.sample_dates, [])
        s = _candidate_stats(r.trades, r.n_candidates)
        self.assertEqual(s["mode"], "full")
        self.assertEqual(s["full_kind"], "candidate_execution")
        self.assertEqual(s["n_candidates"], 0)
        self.assertEqual(s["n_trades"], 0)
        self.assertEqual(s["return_distribution"], [])
        self.assertEqual(s["per_symbol_stats"], [])
        self.assertIsNone(s["profit_factor"])

    def test_last_day_signal_counts_buy_no_next_bar(self) -> None:
        m = _matrix_us(["AAA"], [[10.0]] * 3, [[10.0]] * 3)
        r = simulate_independent(
            m, entries={"AAA": _signals(3, [2])}, exits={"AAA": _signals(3, [])},
            config=MatcherConfig(),
        )
        self.assertEqual(r.n_candidates, 1)
        self.assertEqual(len(r.trades), 0)
        self.assertEqual(r.execution_stats.get("buy_no_next_bar"), 1)


class CandidateStatsTest(unittest.TestCase):
    """stats 口径黄金断言：avg/median/win_rate/profit_factor/total_return/max_dd 手算。"""

    @staticmethod
    def _trade(symbol: str, ret: float, exit_day: int) -> Trade:
        return Trade(
            symbol=symbol, entry_date=_dates(10)[0],
            exit_date=_dates(10)[exit_day],
            entry_price=10.0, exit_price=10.0 * (1 + ret), shares=100.0,
            pnl=ret * 1000.0, ret=ret, exit_reason="signal",
        )

    def test_golden_stats(self) -> None:
        # 3 笔样本：+10%（d2 退出）、-4%（d2 退出）、+5%（d4 退出）
        trades = [
            self._trade("A", 0.10, 2),
            self._trade("B", -0.04, 2),
            self._trade("A", 0.05, 4),
        ]
        s = _candidate_stats(trades, n_candidates=5,
                             benchmark={"symbol": "^GSPC", "total_return": 0.02})
        self.assertEqual(s["mode"], "full")
        self.assertEqual(s["full_kind"], "candidate_execution")
        self.assertEqual(s["n_candidates"], 5)
        self.assertEqual(s["n_trades"], 3)
        self.assertEqual(s["n_closed_days"], 2)  # d2 / d4 两个了结日
        self.assertAlmostEqual(s["avg_daily_closed"], 1.5, places=6)
        self.assertAlmostEqual(s["avg_return"],
                               round((0.10 - 0.04 + 0.05) / 3, 4), places=6)
        self.assertAlmostEqual(s["median_return"], 0.05, places=6)
        self.assertAlmostEqual(s["win_rate"], round(2 / 3, 4), places=6)
        # 盈亏比 = 平均盈利 / 平均亏损 = 0.075 / 0.04
        self.assertAlmostEqual(s["profit_factor"], round(0.075 / 0.04, 2), places=6)
        self.assertAlmostEqual(s["best"], 0.10, places=6)
        self.assertAlmostEqual(s["worst"], -0.04, places=6)
        # 样本收益曲线：d2 平均 (0.10-0.04)/2=0.03 → e1=1.03；d4 0.05 → e2=1.0815
        self.assertAlmostEqual(s["total_return"], round(1.03 * 1.05 - 1, 4), places=6)
        self.assertEqual(s["max_drawdown"], 0.0)  # 曲线单调上行
        self.assertEqual(s["benchmark_symbol"], "^GSPC")
        self.assertAlmostEqual(s["excess_return"],
                               round(1.03 * 1.05 - 1 - 0.02, 4), places=6)
        # 分标的聚合与收益分布（复用 result_stats，结构断言）
        self.assertEqual(len(s["per_symbol_stats"]), 2)
        self.assertEqual(sum(b["count"] for b in s["return_distribution"]), 3)

    def test_profit_factor_none_without_losses(self) -> None:
        trades = [self._trade("A", 0.10, 2), self._trade("B", 0.05, 3)]
        s = _candidate_stats(trades, 2)
        self.assertIsNone(s["profit_factor"])  # 无亏损样本宁缺勿假
        self.assertAlmostEqual(s["win_rate"], 1.0, places=6)

    def test_max_drawdown_on_sample_curve(self) -> None:
        # d2 平均 -20% → e1=0.8；d3 平均 +10% → e2=0.88
        # 回撤轨迹：e1 处 -0.2；e2 处 0.88/1-1 = -0.12 → 最小 -0.2（未收复前高）
        trades = [
            self._trade("A", -0.20, 2),
            self._trade("B", 0.10, 3),
        ]
        s = _candidate_stats(trades, 2)
        self.assertAlmostEqual(s["max_drawdown"], -0.20, places=6)


class ApiRoutingTest(unittest.TestCase):
    """API 层 sim_mode=full 分流：任务 dict 透传 + worker 入口分流（不跑真回测）。"""

    def test_make_backtest_task_carries_sim_mode(self) -> None:
        from app.worker import make_backtest_task

        task = make_backtest_task(["AAA"], "ma_golden_cross", D0, D0, sim_mode="full")
        self.assertEqual(task["sim_mode"], "full")
        default_task = make_backtest_task(["AAA"], "ma_golden_cross", D0, D0)
        self.assertEqual(default_task["sim_mode"], "position")

    def test_backtest_request_accepts_sim_mode(self) -> None:
        from app.api import BacktestRequest

        req = BacktestRequest(strategy_id="s", start=D0, sim_mode="full")
        self.assertEqual(req.sim_mode, "full")
        req2 = BacktestRequest(strategy_id="s", start=D0)
        self.assertEqual(req2.sim_mode, "position")

    def test_worker_entry_dispatches_to_full(self) -> None:
        import queue

        import app.worker as worker_mod

        task = {
            "kind": "backtest", "symbols": ["AAA"],
            "strategy_id": "ma_golden_cross",
            "start": D0.isoformat(), "end": D0.isoformat(),
            "params": None, "config": {}, "user_id": "default",
            "names": None, "sim_mode": "full",
        }
        q: queue.Queue = queue.Queue()
        with mock.patch("app.runner.run_backtest_full",
                        return_value={"stats": {"mode": "full"}}) as full_fn, \
             mock.patch("app.runner.run_backtest") as pos_fn, \
             mock.patch.object(worker_mod.os, "_exit"):  # 真 os._exit 会杀掉测试进程
            worker_mod._worker_entry(task, q)
        self.assertTrue(full_fn.called)
        self.assertFalse(pos_fn.called)
        # 终态消息入队（result 携带 full 模式 stats）
        msgs = []
        while not q.empty():
            msgs.append(q.get_nowait())
        self.assertTrue(any(m.get("type") == "result" for m in msgs))

    def test_worker_entry_default_dispatches_to_position(self) -> None:
        import queue

        import app.worker as worker_mod

        task = {
            "kind": "backtest", "symbols": ["AAA"],
            "strategy_id": "ma_golden_cross",
            "start": D0.isoformat(), "end": D0.isoformat(),
            "params": None, "config": {}, "user_id": "default",
            "names": None,  # 无 sim_mode 键：旧任务兼容，按 position
        }
        q: queue.Queue = queue.Queue()
        with mock.patch("app.runner.run_backtest_full") as full_fn, \
             mock.patch("app.runner.run_backtest",
                        return_value={"stats": {"total_return": 0.0}}) as pos_fn, \
             mock.patch.object(worker_mod.os, "_exit"):
            worker_mod._worker_entry(task, q)
        self.assertTrue(pos_fn.called)
        self.assertFalse(full_fn.called)


if __name__ == "__main__":
    unittest.main()
