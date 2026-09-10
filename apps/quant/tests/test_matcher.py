"""engine.matcher 的回归测试（阶段 G4 移动止损/退出优先级 + H1 分钟成交验收点固化）。

覆盖点（plans/TASKS-QUANT-BACKTEST.md G4/H1 review 记录，全部合成数据 + 注入
minute_loader，不依赖真实 data-api/网络）：
- G4 trailing_stop：冲高 20% 后回落 5% 触发 trailing_stop 离场（峰值跟踪口径：
  peak 初始=entry_price，买入当日 high 不进峰值（买入段在退出段之后执行）；
  持仓次日起每个交易日在退出判定前以当日 high 更新 peak）。
- G4 退出优先级：风控(stop_loss/trailing) > signal > max_hold > end（同日多条成立时
  归因最紧风控线）。
- 判定时机口径：风控触发判定用当日收盘价（ret_now，signal_fired 右移一日的同一日
  i）；成交价按 exit_fill 口径（open_t+1 → 当日开盘价）。即「i-1 日收盘 signal +
  i 日收盘触发止损」为同日竞争，风控优先归因。
- H1 minute_fill：有参考线→穿越价（开盘已穿越→开盘价、盘中触及→参考线、未穿越→收盘
  信号确认价）；无参考线→VWAP；分钟缺失降级日K 口径并计 fallback。
- H1 minute_trigger（exit_fill="signal_next_minute"）：分钟收盘确认下穿触发线 → 下一
  分钟开盘成交（盘中触发早于日K 口径）。
- H1 pending_exit 挂单：signal 当日盘中未确认 → 次日开盘价强制退出（对齐参照
  pending_exit 语义）。⚠ 本用例当前暴露一个真实 app 层 bug（非测试错位，见下注），
  修复前为预期失败——勿为求绿而改断言。
"""
from __future__ import annotations

import unittest
from datetime import date, timedelta

import numpy as np

from app.engine.matcher import MatcherConfig, simulate
from app.matrix import MarketMatrix

D0 = date(2026, 1, 5)


def _dates(n: int) -> list[date]:
    return [D0 + timedelta(days=i) for i in range(n)]


def _matrix(
    opens: list[float],
    closes: list[float],
    highs: list[float] | None = None,
    symbol: str = "AAPL",
) -> MarketMatrix:
    """单列合成市场矩阵（美股标的，避开 CN 涨跌停/T+1/整手干扰）。"""
    n = len(closes)
    close = np.array(closes, dtype=np.float64).reshape(n, 1)
    openp = np.array(opens, dtype=np.float64).reshape(n, 1)
    high = np.array(highs if highs is not None else closes, dtype=np.float64).reshape(n, 1)
    return MarketMatrix(
        dates=_dates(n),
        symbols=[symbol],
        open=openp,
        high=high,
        low=close.copy(),
        close=close,
        volume=np.full((n, 1), 1e6),
        amount=close * 1e6,
    )


def _signals(n: int, fire_days: list[int]) -> np.ndarray:
    """收盘信号 bool 数组（fire_days 为信号产生的日期下标）。"""
    sig = np.zeros(n, dtype=bool)
    for i in fire_days:
        sig[i] = True
    return sig


def _flat_minutes(price: float, bars: int = 4) -> np.ndarray:
    """平直分钟K（全部 OHLC=price），列序 [open, high, low, close, volume, amount]。"""
    return np.tile(np.array([[price, price, price, price, 100.0, price * 100.0]]), (bars, 1))


class TrailingStopTest(unittest.TestCase):
    """G4：移动止损 — 冲高 10% 后回落 5% 触发（参照 tick-stock-panel 口径）。"""

    def test_trailing_stop_fires_after_pullback(self) -> None:
        # 峰值跟踪口径：peak 初始=entry_price；买入当日 high 不进峰值（买入段在
        # 退出段之后执行）；持仓次日起退出判定前以当日 high 更新。场景（下标 i）：
        # i=0 收盘信号 → i=1 开盘 10.0 买入（当日 high=10 不进峰值）；
        # i=2 冲高 12.0（持仓次日，peak 更新为 12，当日 c=12 不触发）；
        # i=3 收盘 11.3 < 12.0×0.95=11.4（跌破 -5% 回撤线）→ 当日按 open_t+1
        # 口径以开盘价 9.9 成交退出。
        m = _matrix(
            opens=[10.0, 10.0, 10.0, 9.9, 10.0],
            closes=[10.0, 10.0, 12.0, 11.3, 11.3],
            highs=[10.0, 10.0, 12.0, 11.3, 11.3],
        )
        r = simulate(
            m,
            entries={"AAPL": _signals(5, [0])},
            exits={"AAPL": _signals(5, [])},
            config=MatcherConfig(trailing_stop_pct=0.05),
        )
        self.assertEqual(len(r.trades), 1)
        t = r.trades[0]
        self.assertEqual(t.exit_reason, "trailing_stop")
        self.assertEqual(t.entry_date, _dates(5)[1])  # i=1 信号次日开盘成交
        self.assertEqual(t.exit_date, _dates(5)[3])  # i=3 触发当日
        self.assertAlmostEqual(t.exit_price, 9.9, places=12)  # i=3 开盘价

    def test_trailing_stop_not_fired_before_activation(self) -> None:
        # 冲高在买入当日（i=1 high=11.0）不进 peak（买入段在退出段之后执行）；
        # peak 停留在 entry 10.0，线 9.5 从不触发 → 期末 end 平仓。
        m = _matrix(
            opens=[10.0, 10.0, 10.0, 10.0],
            closes=[10.0, 10.0, 11.0, 10.5],
            highs=[10.0, 11.0, 11.0, 10.5],
        )
        r = simulate(
            m,
            entries={"AAPL": _signals(4, [0])},
            exits={"AAPL": _signals(4, [])},
            config=MatcherConfig(trailing_stop_pct=0.05),
        )
        self.assertEqual(len(r.trades), 1)
        self.assertEqual(r.trades[0].exit_reason, "end")

    def test_trailing_stop_exact_threshold_not_fired(self) -> None:
        # 边界语义（c <= 线，恰等于不触发）：i=2 冲高 12.0（peak=12）；
        # i=3 收盘 11.4 == 12.0×0.95（浮点精确）→ 不触发，期末 end 平仓。
        m = _matrix(
            opens=[10.0, 10.0, 10.0, 10.0, 10.0],
            closes=[10.0, 10.0, 12.0, 11.4, 11.4],
            highs=[10.0, 10.0, 12.0, 11.4, 11.4],
        )
        r = simulate(
            m,
            entries={"AAPL": _signals(5, [0])},
            exits={"AAPL": _signals(5, [])},
            config=MatcherConfig(trailing_stop_pct=0.05),
        )
        self.assertEqual(len(r.trades), 1)
        self.assertEqual(r.trades[0].exit_reason, "end")


class ExitPriorityTest(unittest.TestCase):
    """G4：退出优先级 — 风控 > signal > max_hold > end。"""

    def test_risk_beats_same_day_signal(self) -> None:
        # 同日竞争：i=1 收盘 signal（signal_fired 右移一日 → i=2 生效）与 i=2 收盘
        # 触发的固定止损（close=9，相对 entry 10 为 -10%，触发 -8% 止损线）在同一
        # 交易日 i=2 判定 → 归因 stop_loss（风控优先），按 open_t+1 口径以当日
        # 开盘价 8.0 成交（止损按开盘价强平、不承担日内继续下行的风险，口径合理）。
        m = _matrix(
            opens=[10.0, 10.0, 8.0, 10.0, 10.0],
            closes=[10.0, 10.0, 9.0, 10.0, 10.0],
        )
        r = simulate(
            m,
            entries={"AAPL": _signals(5, [0])},
            exits={"AAPL": _signals(5, [1])},
            config=MatcherConfig(stop_loss_pct=-0.08),
        )
        self.assertEqual(len(r.trades), 1)
        t = r.trades[0]
        self.assertEqual(t.exit_reason, "stop_loss")
        self.assertEqual(t.exit_date, _dates(5)[2])
        self.assertAlmostEqual(t.exit_price, 8.0, places=12)  # i=2 开盘价

    def test_signal_beats_max_hold(self) -> None:
        # day3 同时满足 signal 与 max_hold（max_hold_days=1：day2 买入、day3 到期）
        # → 归因 signal
        m = _matrix(
            opens=[10.0, 10.0, 10.0, 10.0, 10.0],
            closes=[10.0, 10.0, 10.0, 10.0, 10.0],
        )
        r = simulate(
            m,
            entries={"AAPL": _signals(5, [1])},
            exits={"AAPL": _signals(5, [2])},
            config=MatcherConfig(max_hold_days=1),
        )
        self.assertEqual(len(r.trades), 1)
        self.assertEqual(r.trades[0].exit_reason, "signal")
        self.assertEqual(r.trades[0].exit_date, _dates(5)[3])

    def test_max_hold_beats_end(self) -> None:
        m = _matrix(
            opens=[10.0, 10.0, 10.0, 10.0, 10.0],
            closes=[10.0, 10.0, 10.0, 10.0, 10.0],
        )
        r = simulate(
            m,
            entries={"AAPL": _signals(5, [1])},
            exits={"AAPL": _signals(5, [])},
            config=MatcherConfig(max_hold_days=1),
        )
        self.assertEqual(len(r.trades), 1)
        self.assertEqual(r.trades[0].exit_reason, "max_hold")

    def test_end_of_period_forced_close(self) -> None:
        m = _matrix(
            opens=[10.0, 10.0, 10.0],
            closes=[10.0, 10.0, 11.0],
        )
        r = simulate(
            m,
            entries={"AAPL": _signals(3, [0])},
            exits={"AAPL": _signals(3, [])},
            config=MatcherConfig(),
        )
        self.assertEqual(len(r.trades), 1)
        self.assertEqual(r.trades[0].exit_reason, "end")
        self.assertAlmostEqual(r.trades[0].exit_price, 11.0, places=12)  # 末日收盘强平


class MinuteFillTest(unittest.TestCase):
    """H1：分钟精确成交 — 穿越价 / VWAP / 降级。"""

    def _loader(self, price: float):
        return lambda sym, d: _flat_minutes(price)

    def test_minute_fill_ref_crossed_fill_at_ref(self) -> None:
        # 买入参考线 10.0：当日分钟K 高点触及 → 按参考线 10.0 成交（非日K 开盘 9.5）
        minute = np.array(
            [
                [9.5, 9.6, 9.4, 9.5, 100.0, 950.0],
                [9.6, 10.1, 9.5, 10.0, 100.0, 980.0],
            ]
        )
        m = _matrix(
            opens=[10.0, 9.5, 10.0],
            closes=[10.0, 10.0, 10.0],
        )
        loader = lambda sym, d: minute  # noqa: E731
        r = simulate(
            m,
            entries={"AAPL": _signals(3, [0])},
            exits={"AAPL": _signals(3, [1])},
            config=MatcherConfig(minute_fill=True),
            entry_refs={"AAPL": np.array([10.0, 10.0, 10.0])},
            minute_loader=loader,
        )
        self.assertEqual(len(r.trades), 1)
        self.assertAlmostEqual(r.trades[0].entry_price, 10.0, places=12)
        self.assertEqual(r.trades[0].entry_fill_mode, "minute_ref")
        self.assertEqual(r.minute_entry_used, 1)

    def test_minute_fill_open_already_crossed_fill_at_open(self) -> None:
        # 买入参考线 10.0，当日开盘 10.5 已在线上方 → 按开盘价 10.5 成交
        minute = np.array(
            [
                [10.5, 10.6, 10.4, 10.5, 100.0, 1050.0],
                [10.5, 10.6, 10.4, 10.5, 100.0, 1050.0],
            ]
        )
        m = _matrix(opens=[10.0, 10.5, 10.0], closes=[10.0, 10.0, 10.0])
        r = simulate(
            m,
            entries={"AAPL": _signals(3, [0])},
            exits={"AAPL": _signals(3, [1])},
            config=MatcherConfig(minute_fill=True),
            entry_refs={"AAPL": np.array([10.0, 10.0, 10.0])},
            minute_loader=lambda sym, d: minute,
        )
        self.assertAlmostEqual(r.trades[0].entry_price, 10.5, places=12)
        self.assertEqual(r.trades[0].entry_fill_mode, "minute_ref")

    def test_minute_fill_no_ref_uses_vwap(self) -> None:
        # 无参考线 → VWAP = Σamount / Σvolume = (950+980+1020)/300 = 9.83...
        minute = np.array(
            [
                [9.5, 9.6, 9.4, 9.5, 100.0, 950.0],
                [9.6, 9.9, 9.5, 9.8, 100.0, 980.0],
                [9.8, 10.3, 9.8, 10.2, 100.0, 1020.0],
            ]
        )
        m = _matrix(opens=[10.0, 9.5, 10.0], closes=[10.0, 10.0, 10.0])
        r = simulate(
            m,
            entries={"AAPL": _signals(3, [0])},
            exits={"AAPL": _signals(3, [1])},
            config=MatcherConfig(minute_fill=True),
            minute_loader=lambda sym, d: minute,
        )
        self.assertAlmostEqual(r.trades[0].entry_price, (950 + 980 + 1020) / 300, places=12)
        self.assertEqual(r.trades[0].entry_fill_mode, "minute_vwap")

    def test_minute_fill_missing_minutes_falls_back_to_daily(self) -> None:
        # loader 返回 None → 降级日K 口径（开盘价），fallback 计数 +1
        m = _matrix(opens=[10.0, 9.5, 10.0], closes=[10.0, 10.0, 10.0])
        r = simulate(
            m,
            entries={"AAPL": _signals(3, [0])},
            exits={"AAPL": _signals(3, [1])},
            config=MatcherConfig(minute_fill=True),
            entry_refs={"AAPL": np.array([10.0, 10.0, 10.0])},
            minute_loader=lambda sym, d: None,
        )
        self.assertAlmostEqual(r.trades[0].entry_price, 9.5, places=12)  # 日K 次日开盘
        self.assertEqual(r.trades[0].entry_fill_mode, "daily")
        self.assertEqual(r.minute_entry_fallback, 1)
        self.assertEqual(r.minute_entry_used, 0)


class MinuteTriggerTest(unittest.TestCase):
    """H1：signal_next_minute — 分钟收盘确认下穿触发线 → 下一分钟开盘成交。"""

    def test_intraday_trigger_fills_at_next_minute_open(self) -> None:
        # day3 卖出信号（exit day 下标 2，exit_fill=signal_next_minute 当日盘中确认）：
        # 触发线 ref=10.25（验收记录口径：(5·ma5−close)/4，全部昨日已知量）；
        # 分钟收盘第 2 根确认下穿 → 下一分钟开盘 10.05 成交（早于当日收盘 10.02）
        minute = np.array(
            [
                [10.40, 10.45, 10.35, 10.40, 100.0, 1040.0],
                [10.40, 10.42, 10.10, 10.15, 100.0, 1015.0],  # 收盘 < 10.25 确认下穿
                [10.05, 10.08, 10.00, 10.02, 100.0, 1002.0],  # 下一分钟开盘 10.05
                [10.02, 10.03, 10.01, 10.02, 100.0, 1002.0],
            ]
        )
        n = 4
        m = _matrix(
            opens=[10.0, 10.4, 10.4, 10.0],
            closes=[10.0, 10.4, 10.02, 10.0],
        )
        r = simulate(
            m,
            entries={"AAPL": _signals(n, [0])},
            exits={"AAPL": _signals(n, [2])},
            config=MatcherConfig(exit_fill="signal_next_minute"),
            exit_refs={"AAPL": np.full(n, 10.25)},
            minute_loader=lambda sym, d: minute,
        )
        self.assertEqual(len(r.trades), 1)
        t = r.trades[0]
        self.assertEqual(t.exit_reason, "signal")
        self.assertEqual(t.exit_fill_mode, "minute_trigger")
        self.assertAlmostEqual(t.exit_price, 10.05, places=12)  # 确认点下一分钟开盘
        self.assertEqual(t.exit_date, _dates(n)[2])  # 当日盘中成交
        self.assertEqual(r.minute_exit_used, 1)
        self.assertEqual(r.minute_entry_used, 0)  # 开仓未走分钟口径（计数分离）

    def test_pending_exit_forced_at_next_day_open(self) -> None:
        # signal_next_minute 为当日评估口径：i=3 卖出信号当日盘中未确认（分钟收盘
        # 全程 11.0 在触发线 10.25 上方）→ 当日不成交、置 pending_exit 挂单，
        # 次日（i=4）开盘价 8.0 强制退出（对齐参照 pending_exit 语义，不无限重评估）。
        # 开盘价 8.0 ≠ 收盘价 20.0 刻意拉大差距：锁定强平取开盘价而非收盘价。
        #
        # ⚠ 真实 app 层 bug（2026-09-10 K5 甄别确认，非测试错位）：
        # matcher.py pending_exit 强平分支（约 338 行）用 exit_price_of(i,j) 取价，
        # 而 exit_fill="signal_next_minute"（≠"open_t+1"）时它返回当日收盘价 20.0，
        # 不是次日开盘价 8.0。参照 tick-stock-panel engine.py `_try_close` 对
        # pending_exit_next_open 恒用 matrix.open[time_id]（不看 exit_fill），
        # 本文件 matcher.py 第 264/282/330/405 行注释亦四处声明「次日开盘价强制退出」。
        # 判定为 bug 的依据：①参照实现口径；②本文件自身注释；③验收记录（ff3e5c5）
        #   明确「次日开盘价强制退出」。修复方向：pending_exit 分支改取 openp[i,j]。
        minute = _flat_minutes(11.0)  # 全程 11.0，远高于 ref=10.25，永不确认
        n = 6
        m = _matrix(
            opens=[10.0, 10.0, 10.0, 10.0, 8.0, 10.0],
            closes=[10.0, 10.0, 10.0, 10.0, 20.0, 10.0],
        )
        r = simulate(
            m,
            entries={"AAPL": _signals(n, [1])},
            exits={"AAPL": _signals(n, [3])},
            config=MatcherConfig(exit_fill="signal_next_minute"),
            exit_refs={"AAPL": np.full(n, 10.25)},
            minute_loader=lambda sym, d: minute,
        )
        self.assertEqual(len(r.trades), 1)
        t = r.trades[0]
        self.assertEqual(t.exit_reason, "signal")
        self.assertEqual(t.exit_date, _dates(n)[4])  # 信号次日强平
        self.assertAlmostEqual(t.exit_price, 8.0, places=12)  # 次日开盘价，非收盘 20.0


if __name__ == "__main__":
    unittest.main()
