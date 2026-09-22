"""stats.compute 的 avg_hold_days 交易日口径回归测试（review 缺陷 1）。

旧实现用自然日差 (exit_date - entry_date).days，跨周末/长假系统性偏长
（周五买周一卖自然日=3，实际只隔 1 个交易日）。修复后按净值交易日轴
（equity_dates）的索引差计算；日期不在轴上时防御性回退自然日差。
"""
from __future__ import annotations

import unittest
from datetime import date

from app.engine import stats
from app.engine.matcher import SimResult, Trade

# 交易日轴：2025-01-02（周四）~ 2025-01-07（周二），跳过周末 01-04/01-05
DATES = [date(2025, 1, 2), date(2025, 1, 3), date(2025, 1, 6), date(2025, 1, 7)]


def _trade(entry: date, exit_: date) -> Trade:
    return Trade(
        symbol="X", entry_date=entry, exit_date=exit_,
        entry_price=10.0, exit_price=10.0, shares=100,
        pnl=1.0, ret=0.001, exit_reason="signal",
    )


def _make_result(trades: list[Trade], dates: list[date] | None = None) -> SimResult:
    ds = dates or DATES
    return SimResult(
        trades=trades, equity_dates=ds,
        equity=[100.0] * len(ds), final_value=100.0,
    )


class AvgHoldDaysTradingDayTest(unittest.TestCase):
    def test_weekend_not_counted(self) -> None:
        """周五买、下周一卖：交易日口径 1（旧自然日口径会算成 3）。"""
        r = stats.compute(_make_result([_trade(date(2025, 1, 3), date(2025, 1, 6))]))
        self.assertAlmostEqual(r["avg_hold_days"], 1.0)

    def test_same_day_roundtrip_is_zero(self) -> None:
        """同日进出场为 0 个交易日（轴上同索引差）。"""
        r = stats.compute(_make_result([_trade(date(2025, 1, 6), date(2025, 1, 6))]))
        self.assertAlmostEqual(r["avg_hold_days"], 0.0)

    def test_multi_trade_mean_on_axis(self) -> None:
        """多笔取均值：1 个交易日（跨周末）与 3 个交易日（周四→周二）均值 2。"""
        trades = [
            _trade(date(2025, 1, 3), date(2025, 1, 6)),   # 索引 1→2 = 1
            _trade(date(2025, 1, 2), date(2025, 1, 7)),   # 索引 0→3 = 3
        ]
        r = stats.compute(_make_result(trades))
        self.assertAlmostEqual(r["avg_hold_days"], 2.0)

    def test_fallback_to_calendar_days_when_off_axis(self) -> None:
        """成交日期不在净值交易日轴上（防御分支）：回退自然日差，不抛错。"""
        # 01-05 是周日，不在 DATES 轴上 → 回退 (01-06 - 01-05).days = 1
        r = stats.compute(_make_result([_trade(date(2025, 1, 5), date(2025, 1, 6))]))
        self.assertAlmostEqual(r["avg_hold_days"], 1.0)

    def test_short_equity_no_crash(self) -> None:
        """净值曲线不足 2 条走空骨架，avg_hold_days=0（降级不崩）。"""
        r = stats.compute(
            _make_result([_trade(date(2025, 1, 3), date(2025, 1, 6))], dates=DATES[:1])
        )
        self.assertEqual(r["avg_hold_days"], 0.0)


if __name__ == "__main__":
    unittest.main()
