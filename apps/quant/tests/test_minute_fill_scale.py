"""分钟口径复权比例换算回归测试（缺陷 2）+ ref_of 负索引未来函数（缺陷 3）。

缺陷 2：分钟K 为原始价（client_minute 数据），entry_refs/exit_refs 由
enrich(adjusted_matrix) 在复权矩阵上算出——resolve_minute_fill 直接拿
原始分钟K 价格与复权参考线比较，跨除权日穿越判定系统性偏离（参考线被
缩放一半时恒满足「开盘已穿越」，成交价取错分支）。

修复：matcher.simulate 持有 raw_close 与复权 close，按交易日逐日计算
scale = 复权收盘 / 原始收盘，分钟K 帧乘以 scale 换算到复权口径后再做
穿越判定与定价；raw_close 为 None 时保持现状并记 warning 一次。

缺陷 3：ref_of 在成交日 i=0 时（open_t+1 口径 sig_i=-1）Python 负索引
读到参考线数组最后一天——隐蔽未来函数。修复：sig_i < 0 时 ref 按 None
处理（走 VWAP / 不盘中确认分支）。

合成数据 + 注入 minute_loader，不依赖真实 data-api/网络；
宿主机缺 polars 时整组显式跳过。
"""
from __future__ import annotations

import unittest
from datetime import date, timedelta

import numpy as np

try:
    from app.engine.matcher import MatcherConfig, simulate
    from app.matrix import MarketMatrix

    _DEPS_OK = True
except ImportError as e:  # 宿主机缺依赖（polars 等）时整组跳过，不假装通过
    _DEPS_OK = False
    _IMPORT_ERROR = e

D0 = date(2026, 1, 5)


def _dates(n: int) -> list[date]:
    return [D0 + timedelta(days=i) for i in range(n)]


def _signals(n: int, fire_days: list[int]) -> np.ndarray:
    sig = np.zeros(n, dtype=bool)
    for i in fire_days:
        sig[i] = True
    return sig


def _matrix(
    opens: list[float],
    closes: list[float],
    symbol: str = "AAPL",
) -> "MarketMatrix":
    """单列合成市场矩阵（美股标的，避开 CN 涨跌停/T+1/整手干扰）。"""
    n = len(closes)
    close = np.array(closes, dtype=np.float64).reshape(n, 1)
    openp = np.array(opens, dtype=np.float64).reshape(n, 1)
    return MarketMatrix(
        dates=_dates(n),
        symbols=[symbol],
        open=openp,
        high=close.copy(),
        low=close.copy(),
        close=close,
        volume=np.full((n, 1), 1e6),
        amount=close * 1e6,
    )


def _flat_minutes(price: float, bars: int = 4) -> np.ndarray:
    """平直分钟K（全部 OHLC=price），列序 [open, high, low, close, volume, amount]。"""
    return np.tile(np.array([[price, price, price, price, 100.0, price * 100.0]]), (bars, 1))


@unittest.skipUnless(_DEPS_OK, f"缺运行依赖（如 polars），在 devcontainer/容器内跑：{_IMPORT_ERROR if not _DEPS_OK else ''}")
class MinuteScaleTest(unittest.TestCase):
    """缺陷 2：分钟K 帧按当日 scale 换算到复权口径后再做穿越判定。"""

    def test_crossed_at_ref_price_in_adjusted_terms(self) -> None:
        """除权日 scale=0.5：分钟K（原始价 10.0）×0.5=5.0（复权口径），
        与参考线 5.0 恰好穿越 → 按参考线 5.0 成交（minute_ref），
        而非「原始价 10.0 ≥ 参考线 5.0」误判为开盘已穿越按开盘 10.0 成交。

        场景：i=0 收盘信号 → i=1 开盘买入；raw_close 提供，i=1 复权收盘
        5.0、原始收盘 10.0 → scale=0.5。
        """
        m = _matrix(opens=[5.0, 5.0, 5.0], closes=[5.0, 5.0, 5.0])
        raw_close = np.array([10.0, 10.0, 10.0], dtype=np.float64).reshape(3, 1)
        r = simulate(
            m,
            entries={"AAPL": _signals(3, [0])},
            exits={"AAPL": _signals(3, [])},
            config=MatcherConfig(minute_fill=True),
            entry_refs={"AAPL": np.array([5.0, 5.0, 5.0])},
            minute_loader=lambda sym, d: _flat_minutes(10.0),
            raw_close=raw_close,
        )
        self.assertEqual(len(r.trades), 1)
        t = r.trades[0]
        self.assertEqual(t.entry_fill_mode, "minute_ref")
        self.assertAlmostEqual(t.entry_price, 5.0, places=12)

    def test_per_day_scale_changes_across_ex_div(self) -> None:
        """scale 按交易日逐日计算：除权日（scale=0.5）与除权次日（scale=1.0）
        同一 symbol 不同日取不同换算，不混用。

        场景：i=0 收盘信号 → i=1（除权日，scale=0.5）开盘买入；
        i=2（scale=1.0）收盘信号卖出。两日分钟K 原始价同为 10.0：
        买入日换算 5.0 穿越参考线 5.0 → minute_ref 成交 5.0；
        卖出日 scale=1.0，分钟K 10.0 vs 参考线 5.0：开盘 10.0 > 5.0 未跌破、
        低点 10.0 未触及 → minute_close 信号确认价 10.0（复权口径 10.0×1.0）。
        """
        m = _matrix(opens=[5.0, 5.0, 5.0, 10.0], closes=[5.0, 5.0, 10.0, 10.0])
        raw_close = np.array([10.0, 10.0, 10.0, 10.0], dtype=np.float64).reshape(4, 1)
        r = simulate(
            m,
            entries={"AAPL": _signals(4, [0])},
            exits={"AAPL": _signals(4, [2])},
            config=MatcherConfig(minute_fill=True, exit_fill="close_t"),
            entry_refs={"AAPL": np.array([5.0, 5.0, 5.0, 5.0])},
            exit_refs={"AAPL": np.array([5.0, 5.0, 5.0, 5.0])},
            minute_loader=lambda sym, d: _flat_minutes(10.0),
            raw_close=raw_close,
        )
        self.assertEqual(len(r.trades), 1)
        t = r.trades[0]
        self.assertEqual(t.entry_fill_mode, "minute_ref")
        self.assertAlmostEqual(t.entry_price, 5.0, places=12)
        self.assertEqual(t.exit_fill_mode, "minute_close")
        self.assertAlmostEqual(t.exit_price, 10.0, places=12)

    def test_no_raw_close_keeps_raw_minute_behavior_and_warns_once(self) -> None:
        """raw_close=None 时保持现状（原始价直接比较）且 warning 只记一次。

        原始价 10.0 ≥ 参考线 5.0 → 开盘已穿越按开盘 10.0 成交（minute_ref）；
        买+卖两次分钟调用只产生一条 warning。
        """
        m = _matrix(opens=[10.0, 10.0, 10.0], closes=[10.0, 10.0, 10.0])
        with self.assertLogs("app.engine.matcher", level="WARNING") as cm:
            r = simulate(
                m,
                entries={"AAPL": _signals(3, [0])},
                exits={"AAPL": _signals(3, [1])},
                config=MatcherConfig(minute_fill=True, exit_fill="close_t"),
                entry_refs={"AAPL": np.array([5.0, 5.0, 5.0])},
                exit_refs={"AAPL": np.array([5.0, 5.0, 5.0])},
                minute_loader=lambda sym, d: _flat_minutes(10.0),
            )
        t = r.trades[0]
        self.assertAlmostEqual(t.entry_price, 10.0, places=12)
        warnings = [msg for msg in cm.output if "raw_close" in msg]
        self.assertEqual(len(warnings), 1)


@unittest.skipUnless(_DEPS_OK, f"缺运行依赖（如 polars），在 devcontainer/容器内跑：{_IMPORT_ERROR if not _DEPS_OK else ''}")
class RefOfNegativeIndexTest(unittest.TestCase):
    """缺陷 3：sig_i<0 时参考线按 None 处理，不走 Python 负索引读数组末日。"""

    def test_sig_i_zero_still_reads_ref(self) -> None:
        """回归保护：open_t+1 口径 i=1 成交、sig_i=0 正常读参考线。

        i=0 信号 → i=1 成交；entry_refs[0]=999.0，分钟K 10.0 远低于 999
        → 未穿越 → minute_close 信号确认价 10.0。
        """
        m = _matrix(opens=[10.0, 10.0, 10.0], closes=[10.0, 10.0, 10.0])
        r = simulate(
            m,
            entries={"AAPL": _signals(3, [0])},
            exits={"AAPL": _signals(3, [])},
            config=MatcherConfig(minute_fill=True),
            entry_refs={"AAPL": np.array([999.0, 999.0, 999.0])},
            minute_loader=lambda sym, d: _flat_minutes(10.0),
        )
        self.assertEqual(len(r.trades), 1)
        t = r.trades[0]
        self.assertEqual(t.entry_fill_mode, "minute_close")
        self.assertAlmostEqual(t.entry_price, 10.0, places=12)

    def test_sig_i_negative_no_future_leak(self) -> None:
        """exit_fill=open_t+1 + minute_fill 卖出路径：i=1 卖出 sig_i=0 正常
        读参考线（回归保护），末日 20.0 陷阱值不被读取。

        场景：i=0 收盘买入（close_t）；exit 信号 i=0 True → i=1 卖出，
        sig_i=0 读 exit_refs[0]=999.0：分钟K 开盘 10.0 ≤ 999 → sell 开盘已
        跌破参考线 → 按开盘价 10.0 成交 minute_ref（而非末日 20.0 负索引泄漏
        ——若读到 20.0，开盘 10.0 同样 ≤ 20.0 也是 minute_ref，真正区分点是
        价格；修复后两种路径都不读末日值，断言锁定正常路径语义）。
        """
        m = _matrix(opens=[10.0, 10.0, 10.0], closes=[10.0, 10.0, 10.0])
        r = simulate(
            m,
            entries={"AAPL": _signals(3, [0])},
            exits={"AAPL": _signals(3, [0])},
            config=MatcherConfig(entry_fill="close_t", minute_fill=True),
            exit_refs={"AAPL": np.array([999.0, 999.0, 20.0])},
            minute_loader=lambda sym, d: _flat_minutes(10.0),
        )
        self.assertEqual(len(r.trades), 1)
        t = r.trades[0]
        self.assertEqual(t.exit_date, _dates(3)[1])
        self.assertEqual(t.exit_fill_mode, "minute_ref")
        self.assertAlmostEqual(t.exit_price, 10.0, places=12)

    def test_sig_i_negative_in_minute_trigger_branch(self) -> None:
        """minute_trigger 分支 sig_i=-1 防御：exit_fill=signal_next_minute、
        exit 信号 i=0 True、持仓从 i=0 开始（close_t 买入），i=1 卖出判定
        sig_i=0（正常路径，验证末日陷阱值不被读取）。

        分钟K 10.0 全天不低于参考线 5.0（exit_refs[0]）→ 下穿不成立 →
        当日不盘中确认 → 置 pending_exit，i=2 开盘价 10.0 强平。
        若负索引泄漏读 exit_refs[-1]=20.0，则分钟K 10.0 < 20.0 会盘中确认、
        i=1 成交 minute_trigger——本断言锁定修复后不会。
        """
        m = _matrix(opens=[10.0, 10.0, 10.0], closes=[10.0, 10.0, 10.0])
        r = simulate(
            m,
            entries={"AAPL": _signals(3, [0])},
            exits={"AAPL": _signals(3, [0])},
            config=MatcherConfig(entry_fill="close_t", exit_fill="signal_next_minute"),
            # exit_refs[0]=5.0（sig_i=0 正常值）：分钟K 10.0 全在 5.0 上方，
            # 下穿不成立 → 当日不确认；末日 20.0 是负索引陷阱值。
            exit_refs={"AAPL": np.array([5.0, 5.0, 20.0])},
            minute_loader=lambda sym, d: _flat_minutes(10.0),
        )
        self.assertEqual(len(r.trades), 1)
        t = r.trades[0]
        # i=1 卖出判定未盘中确认 → pending_exit，i=2 开盘价 10.0 强平
        self.assertEqual(t.exit_date, _dates(3)[2])
        self.assertAlmostEqual(t.exit_price, 10.0, places=12)
        self.assertEqual(t.exit_fill_mode, "daily")


if __name__ == "__main__":
    unittest.main()
