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
- 分钟卖出跌停拦截：minute_trigger 分支成交前查 blocked_by_limit(sell)，跌停日
  不成交、置 pending_exit，次日开盘价强平。
- 状态型信号重触发防护：风控类退出（stop_loss 等）后置冷却标记，entry 信号须先
  复位（False）再触发（沿）才允许重新开仓；signal 退出不冷却。
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


class MinuteTriggerLimitBlockTest(unittest.TestCase):
    """分钟卖出路径跌停拦截：minute_trigger 成交前查 blocked_by_limit(sell)。"""

    def test_limit_down_day_blocks_minute_trigger_exit(self) -> None:
        # CN 主板（600001.SH，±10%）：i=3 收盘 9.0 = 昨收 10.0 × 0.9 一字跌停，
        # 当日分钟K 已确认下穿触发线（分钟口径本应成交 8.5）——但跌停不可卖出：
        # 不成交、置 pending_exit，次日（i=4）开盘价 9.2 强制退出。
        # signal_next_minute 为当日盘中确认口径：exits 信号在 i=3 当日判定
        # （signal_fired 不右移），entry 口径仍为 open_t+1（i=1 信号 → i=2 买入）。
        n = 6
        trigger_minute = np.array(
            [
                [9.5, 9.6, 9.4, 9.5, 100.0, 950.0],
                [9.2, 9.3, 9.0, 9.1, 100.0, 910.0],  # 收盘 < 9.2 确认下穿
                [8.5, 8.6, 8.4, 8.5, 100.0, 850.0],  # 下一分钟开盘 8.5
                [8.6, 8.7, 8.5, 8.6, 100.0, 860.0],
            ]
        )
        flat_minute = _flat_minutes(9.5)

        def loader(sym: str, d: date) -> np.ndarray:
            return trigger_minute if d == _dates(n)[3] else flat_minute

        m = _matrix(
            opens=[10.0, 10.0, 10.0, 9.4, 9.2, 10.0],
            closes=[10.0, 10.0, 10.0, 9.0, 9.3, 10.0],
            symbol="600001.SH",
        )
        r = simulate(
            m,
            entries={"600001.SH": _signals(n, [1])},
            exits={"600001.SH": _signals(n, [3])},  # signal 于 i=3 当日盘中确认
            config=MatcherConfig(exit_fill="signal_next_minute"),
            exit_refs={"600001.SH": np.full(n, 9.2)},
            minute_loader=loader,
        )
        self.assertEqual(len(r.trades), 1)
        t = r.trades[0]
        self.assertEqual(t.exit_reason, "signal")
        self.assertEqual(t.exit_date, _dates(n)[4])  # 跌停日未成交，次日强平
        self.assertAlmostEqual(t.exit_price, 9.2, places=12)  # 次日开盘价
        self.assertEqual(r.minute_exit_used, 0)  # 分钟触发被跌停拦截，未成交


class StatefulEntryCooldownTest(unittest.TestCase):
    """状态型信号重触发防护：风控退出后冷却，信号复位后再沿触发才允许重开仓。"""

    def test_stop_loss_exit_cooldown_until_signal_resets(self) -> None:
        # 状态型 entry 信号：i=0..2 连续 True，i=3 False（复位），i=4 True（新沿）。
        # i=1 开盘 10.0 买入；i=2 收盘 9.0（-10%）触发 stop_loss（-8%），当日
        # 开盘 9.2 平仓；i=3 信号仍 True 但因冷却不重开仓；i=4 信号 False 复位
        # 冷却；i=5 信号新沿 → 开盘 9.5 重新开仓，期末 end 平仓。
        # 无防护时 i=3 会立即以 9.0 重开仓（共 3 笔交易），锁定防护行为。
        n = 6
        m = _matrix(
            opens=[10.0, 10.0, 9.2, 9.0, 9.4, 9.5],
            closes=[10.0, 10.0, 9.0, 9.2, 9.4, 9.6],
        )
        r = simulate(
            m,
            entries={"AAPL": _signals(n, [0, 1, 2, 4])},
            exits={"AAPL": _signals(n, [])},
            config=MatcherConfig(stop_loss_pct=-0.08),
        )
        self.assertEqual(len(r.trades), 2)
        t1, t2 = r.trades
        self.assertEqual(t1.exit_reason, "stop_loss")
        self.assertEqual(t1.exit_date, _dates(n)[2])
        self.assertEqual(t2.entry_date, _dates(n)[5])  # 信号复位后新沿才重开仓
        self.assertEqual(t2.exit_reason, "end")

    def test_signal_exit_no_cooldown_reentry_allowed(self) -> None:
        # signal 退出不冷却：i=2 收盘 exit 信号于 i=3 开盘 9.5 退出；同日 i=3
        # entry 信号（i=2 收盘产生，右移一日）仍 True 且未冷却 → 先卖后买，
        # 退出当日立即以 9.5 重开仓（状态型信号未复位也能进），期末 end 平仓。
        # 有冷却时当日会被拦下（信号此后无 False 复位，永不重开仓，只 1 笔交易）。
        n = 5
        m = _matrix(
            opens=[10.0, 10.0, 10.0, 9.5, 9.5],
            closes=[10.0, 10.0, 10.0, 9.5, 9.6],
        )
        r = simulate(
            m,
            entries={"AAPL": _signals(n, [0, 1, 2, 3])},
            exits={"AAPL": _signals(n, [2])},
            config=MatcherConfig(),
        )
        self.assertEqual(len(r.trades), 2)
        t1, t2 = r.trades
        self.assertEqual(t1.exit_reason, "signal")
        self.assertEqual(t1.exit_date, _dates(n)[3])  # i=2 信号 → i=3 开盘退出
        self.assertEqual(t2.entry_date, _dates(n)[3])  # 信号仍 True，退出当日即重开仓
        self.assertEqual(t2.exit_reason, "end")


if __name__ == "__main__":
    unittest.main()


class MetaRiskMergeTest(unittest.TestCase):
    """P0 修复：策略 META 声明的 stop_loss/max_hold_days 必须真正进入撮合。

    此前 api_backtest 构造 MatcherConfig 时只传资金/佣金/分钟口径，runner 用
    `config or MatcherConfig()` 直透——META 风控形同虚设（review P0）。
    """

    def test_meta_stop_loss_merged_into_matcher_config(self) -> None:
        from app.runner import _merge_meta_risk
        from app.engine import MatcherConfig

        class _FakeDef:
            stop_loss = -0.06
            max_hold_days = 15
            meta = {"stop_loss": -0.06, "max_hold_days": 15}

        cfg = _merge_meta_risk(None, _FakeDef())
        self.assertEqual(cfg.stop_loss_pct, -0.06)
        self.assertEqual(cfg.max_hold_days, 15)

    def test_explicit_config_overrides_meta(self) -> None:
        from app.runner import _merge_meta_risk
        from app.engine import MatcherConfig

        class _FakeDef:
            stop_loss = -0.06
            max_hold_days = 15
            meta = {"stop_loss": -0.06, "max_hold_days": 15}

        cfg = _merge_meta_risk(MatcherConfig(stop_loss_pct=-0.10), _FakeDef())
        # 显式 config 优先：stop_loss 用 -0.10，max_hold_days 仍回填 META
        self.assertEqual(cfg.stop_loss_pct, -0.10)
        self.assertEqual(cfg.max_hold_days, 15)

    def test_meta_trailing_fields_merged(self) -> None:
        from app.runner import _merge_meta_risk

        class _FakeDef:
            stop_loss = None
            max_hold_days = None
            meta = {"trailing_stop_pct": 0.05}

        cfg = _merge_meta_risk(None, _FakeDef())
        self.assertEqual(cfg.trailing_stop_pct, 0.05)

    def test_no_meta_risk_keeps_config_unchanged(self) -> None:
        from app.runner import _merge_meta_risk
        from app.engine import MatcherConfig

        class _FakeDef:
            stop_loss = None
            max_hold_days = None
            meta = {}

        cfg_in = MatcherConfig(initial_capital=500_000.0)
        cfg = _merge_meta_risk(cfg_in, _FakeDef())
        self.assertIs(cfg, cfg_in)  # 无 META 风控时原样返回（不 replace）

    def test_end_to_end_stop_loss_fires_in_simulation(self) -> None:
        """集成：META stop_loss 并入后，合成矩阵上止损真正触发。"""
        from app.runner import _merge_meta_risk

        class _FakeDef:
            stop_loss = -0.05
            max_hold_days = None
            meta = {"stop_loss": -0.05}

        # 买入后跌 6%（触发 -5% 止损）
        opens = [10.0, 10.0, 9.4, 9.4, 9.4]
        closes = [10.0, 10.0, 9.4, 9.4, 9.4]
        m = _matrix(opens, closes)
        entry = np.zeros(5, dtype=bool)
        entry[0] = True  # 首日信号
        cfg = _merge_meta_risk(
            MatcherConfig(entry_fill="close_t", exit_fill="close_t"), _FakeDef()
        )
        result = simulate(m, {"AAPL": entry}, {"AAPL": np.zeros(5, dtype=bool)}, cfg)
        reasons = [t.exit_reason for t in result.trades]
        self.assertIn("stop_loss", reasons)


class SmallCapitalBudgetTest(unittest.TestCase):
    """P1-3 修复：小本金（initial_capital < 1000）下 CN min_commission 不应压垮开仓预算。

    修复前 cost_rate = buy_cost(1.0) = max(0.00025, 5.0) + slippage ≈ 501%，
    cash / (1 + 5.01) 把预算砍掉 83%，小本金 alloc<=0 永远开不了仓。
    修复后 cost_rate 用 budget 量级估算（buy_cost(budget)/budget），
    min_commission 在万元级预算下占比 <0.1%，不再压垮。
    """

    def test_small_capital_cn_stock_can_open_position(self) -> None:
        # CN 标的 + 小本金（10 万元，A 股散户常见量级）
        opens = [10.0] * 5
        closes = [10.0] * 5
        m = _matrix(opens, closes, symbol="600519.SH")
        entry = np.zeros(5, dtype=bool)
        entry[0] = True
        cfg = MatcherConfig(
            entry_fill="close_t", exit_fill="close_t",
            initial_capital=100_000.0,  # 10 万元
            max_positions=1,
        )
        result = simulate(m, {"600519.SH": entry}, {"600519.SH": np.zeros(5, dtype=bool)}, cfg)
        # 修复前：cost_rate=501% → alloc≈cash/6≈1.6万 → 整手 100 股 × 10 元 = 1000 元
        # 能开仓但预算被砍 83%；修复后：cost_rate≈0.05% → alloc≈cash → 整手满仓
        self.assertEqual(len(result.trades), 1)  # 期末强平
        # 仓位市值应接近全部本金（整手约束下 <5% 误差）
        trade = result.trades[0]
        position_value = trade.shares * trade.entry_price
        self.assertGreater(position_value / 100_000.0, 0.90)


class CloseTMinuteTriggerTest(unittest.TestCase):
    """P2-7：close_t 口径的组合边界 — 冷却复位用 sig_i=i（当日信号值）。

    open_t+1 口径的冷却/沿触发交错已由 StatefulEntryCooldownTest 钉住；
    本类补 close_t 口径（复位与 signal_fired 的 sig_i 均为 i 而非 i-1）
    与分钟触发卖出组合下的两条路径，并确认 signal 退出不冷却的语义
    在 close_t 口径下与 open_t+1 一致。
    """

    def test_close_t_signal_next_minute_exit_no_cooldown(self) -> None:
        # entry 信号 i=0 True（close_t 口径当日收盘 100.0 成交）；
        # exit 信号 i=2 True（signal_next_minute：当日分钟收盘确认下穿
        # 触发线 99.5 → 下一分钟开盘 98.8 盘中成交，早于当日收盘 99.0）；
        # entry 信号 i=3 再 True：signal 退出不冷却，新沿当日即重开仓。
        minute = np.array(
            [
                [100.0, 100.2, 99.8, 100.0, 100.0, 10000.0],
                [99.8, 99.9, 99.0, 99.2, 100.0, 9920.0],   # 收盘 < 99.5 确认下穿
                [98.8, 99.0, 98.6, 98.8, 100.0, 9880.0],   # 下一分钟开盘 98.8
                [98.8, 98.9, 98.7, 98.8, 100.0, 9880.0],
            ]
        )
        n = 5
        m = _matrix(
            opens=[100.0, 100.0, 99.0, 99.0, 99.0],
            closes=[100.0, 100.0, 99.0, 99.0, 99.0],
            symbol="600519.SH",
        )
        r = simulate(
            m,
            entries={"600519.SH": _signals(n, [0, 3])},
            exits={"600519.SH": _signals(n, [2])},
            config=MatcherConfig(entry_fill="close_t", exit_fill="signal_next_minute"),
            exit_refs={"600519.SH": np.full(n, 99.5)},
            minute_loader=lambda sym, d: minute,
        )
        self.assertEqual(len(r.trades), 2)
        t1, t2 = r.trades
        # 买入走 close_t 口径：信号当日（i=0）收盘价成交
        self.assertEqual(t1.entry_date, _dates(n)[0])
        self.assertAlmostEqual(t1.entry_price, 100.0, places=12)
        # 卖出走分钟触发：i=2 盘中确认，下一分钟开盘 98.8 成交
        self.assertEqual(t1.exit_reason, "signal")
        self.assertEqual(t1.exit_fill_mode, "minute_trigger")
        self.assertEqual(t1.exit_date, _dates(n)[2])
        self.assertAlmostEqual(t1.exit_price, 98.8, places=12)
        self.assertEqual(r.minute_exit_used, 1)
        # signal 退出不冷却：i=3 新信号沿当日即重开仓（与 open_t+1 行为一致）
        self.assertEqual(t2.entry_date, _dates(n)[3])
        self.assertEqual(t2.exit_reason, "end")

    def test_close_t_stop_loss_cooldown_reset_by_today_signal(self) -> None:
        # 脉冲型 entry 信号 [T,F,F,T]：i=0 收盘 100.0 买入（close_t 口径）；
        # i=1 收盘 91.0（-9%）触发 stop_loss=-0.08 平仓并置冷却；
        # i=2 复位检查读 entries[2]=False（sig_i=i 当日口径）→ 冷却复位；
        # i=3 信号新沿 → 当日收盘 91.0 重开仓，不被冷却拦。
        # 复位时序细节：复位检查在每日循环顶部、止损置冷却在当日平仓段，
        # 故止损当日（i=1）的 False 在冷却置位前已被消费，复位由止损次日
        # （i=2）的 False 完成——这正是 close_t 与 open_t+1（sig_i=i-1，
        # 复位读昨日信号）交错的差异点。
        n = 5
        m = _matrix(
            opens=[100.0, 91.0, 91.0, 91.0, 91.0],
            closes=[100.0, 91.0, 91.0, 91.0, 91.0],
            symbol="600519.SH",
        )
        r = simulate(
            m,
            entries={"600519.SH": _signals(n, [0, 3])},
            exits={"600519.SH": _signals(n, [])},
            config=MatcherConfig(entry_fill="close_t", stop_loss_pct=-0.08),
        )
        self.assertEqual(len(r.trades), 2)
        t1, t2 = r.trades
        # i=1 止损平仓（-9% 跌破 -8% 线），冷却置位
        self.assertEqual(t1.exit_reason, "stop_loss")
        self.assertEqual(t1.exit_date, _dates(n)[1])
        self.assertAlmostEqual(t1.exit_price, 91.0, places=12)
        # 冷却已复位（i=2 信号 False）→ i=3 沿触发正常重开仓，期末强平
        self.assertEqual(t2.entry_date, _dates(n)[3])
        self.assertAlmostEqual(t2.entry_price, 91.0, places=12)  # close_t 当日收盘
        self.assertEqual(t2.exit_reason, "end")
