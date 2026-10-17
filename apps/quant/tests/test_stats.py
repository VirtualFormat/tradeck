"""stats.compute 的黄金参考值测试（阶段 K2 对账固化）。

对账方式（2026-09-10）：原计划与 empyrical 对账，但其 setup.py 用了 Python 3.12
已移除的 configparser.SafeConfigParser（0.5.5 及更老版本均装不上，empyrical-reload
fork 也不可达），改为手工推导期望值 + numpy 第二实现（显式按定义逐步展开）对拍。

口径核对结论（与常见第三方库如 empyrical 的差异）：
- annual_return：几何 CAGR，(末值/首值)^(252/收益条数) - 1，与 empyrical 一致。
- max_drawdown：净值/历史峰值 - 1 的最小值，与 empyrical 一致（相对回撤口径）。
- calmar：年化 / |最大回撤|，与 empyrical 一致。
- sharpe：tradeck 用 ddof=0（总体标准差），empyrical 默认 ddof=1（样本标准差），
  换算 sharpe_ddof0 = sharpe_ddof1 × √(n/(n-1))，属口径差异而非错误。
- sortino：tradeck 用负收益样本的 ddof=0 标准差，empyrical 用相对年化目标收益的
  下行偏差，属口径差异。
- 无风险利率统一取 0，结果字典里以 risk_free_rate 字段标注。

参考值均为手工推导（手算值），不依赖任何第三方统计库。
"""
from __future__ import annotations

import math
import unittest
from datetime import date, timedelta

from app.engine.matcher import SimResult, Trade
from app.engine import stats


def _make_result(
    equity: list[float],
    trades: list[Trade] | None = None,
) -> SimResult:
    d0 = date(2025, 1, 2)
    return SimResult(
        trades=trades or [],
        equity_dates=[d0 + timedelta(days=i) for i in range(len(equity))],
        equity=list(equity),
        final_value=equity[-1] if equity else 0.0,
    )


class GeometricMetricsTest(unittest.TestCase):
    """固定净值序列 + 手算黄金值（净值口径指标）。"""

    # 场景 A：先 +50% 再 -50% 回到 75，回撤恰为 -0.5，各值可精确手算。
    EQUITY_DRAWDOWN = [100.0, 150.0, 75.0]

    def test_max_drawdown_and_total_return_hand_calc(self) -> None:
        r = stats.compute(_make_result(self.EQUITY_DRAWDOWN))
        # 回撤 = 75/150 - 1 = -0.5；总收益 = 75/100 - 1 = -0.25
        self.assertAlmostEqual(r["max_drawdown"], -0.5, places=12)
        self.assertAlmostEqual(r["total_return"], -0.25, places=12)
        # 年化 = 0.75^(252/2) - 1 = 0.75^126 - 1
        self.assertAlmostEqual(r["annual_return"], 0.75 ** 126 - 1.0, places=12)
        # calmar = 年化 / |回撤|
        self.assertAlmostEqual(r["calmar"], (0.75 ** 126 - 1.0) / 0.5, places=12)

    # 场景 B：±10% 对称交替收益（日收益恰为 ±0.1，乘法顺序无关，
    # 净值手算为 100×1.1^k×0.9^m）。10 条收益均值恰为 0、
    # ddof=0 标准差恰为 0.1；几何末值 = 100×0.99^5。
    # 刻意选收益为精确可表示的小数（0.1 浮点近似在净值链中相乘即得参考值），
    # 使 total_return 可用 0.99^5 精确对照。
    EQUITY_FLAT = [100.0]
    _v = 100.0
    for _i in range(10):
        _v *= 1.1 if _i % 2 == 0 else 0.9
        EQUITY_FLAT.append(_v)

    def test_symmetric_returns_hand_calc(self) -> None:
        r = stats.compute(_make_result(self.EQUITY_FLAT))
        # 均值为 0 → sharpe = 0（浮点累加残差 <1e-8）；
        # 10 条收益各 ±0.1，ddof=0 标准差 = 0.1 → 年化波动 = √252×0.1
        self.assertAlmostEqual(r["sharpe"], 0.0, places=8)
        self.assertAlmostEqual(r["annual_volatility"], math.sqrt(252) * 0.1, places=9)
        # 末值 = 100×0.99^5，与手算参考同一条浮点乘法链 → 可严格对齐
        self.assertAlmostEqual(r["total_return"], self.EQUITY_FLAT[-1] / 100.0 - 1.0, places=12)
        expected_total = self.EQUITY_FLAT[-1] / 100.0 - 1.0
        self.assertAlmostEqual(
            r["annual_return"], (1.0 + expected_total) ** 25.2 - 1.0, places=12
        )
        # 峰值为 110（第 2 点），谷底为末值，回撤手算为两者之比 - 1
        self.assertAlmostEqual(
            r["max_drawdown"], self.EQUITY_FLAT[-1] / 110.0 - 1.0, places=12
        )

    def test_sortino_hand_calc(self) -> None:
        # 独立场景：收益序列 [+0.10, -0.04, -0.06, +0.02]，
        # 均值 0.005；负样本 [-0.04, -0.06] 的 ddof=0 标准差 = 0.01（手算）。
        rets = [0.10, -0.04, -0.06, 0.02]
        eq = [100.0]
        v = 100.0
        for x in rets:
            v *= 1.0 + x
            eq.append(v)
        r = stats.compute(_make_result(eq))
        # sortino = 0.005 / 0.01 × √252 = 0.5√252（与手算参考同一条除法链）
        neg = [-0.04, -0.06]
        neg_mean = sum(neg) / 2
        neg_std = math.sqrt(sum((x - neg_mean) ** 2 for x in neg) / 2)
        expected = (sum(rets) / 4) / neg_std * math.sqrt(252)
        self.assertAlmostEqual(r["sortino"], expected, places=9)
        # 负样本标准差恰为 0.01，断言 sortino ≈ 0.5√252 到 6 位
        self.assertAlmostEqual(r["sortino"], 0.5 * math.sqrt(252), places=6)

    # 场景 C：每日恒 -1%，校验几何链与 calmar。
    EQUITY_DOWN = [100.0, 99.0, 98.01, 97.0299]

    def test_constant_decline_hand_calc(self) -> None:
        r = stats.compute(_make_result(self.EQUITY_DOWN))
        # 总收益 = 0.99^3 - 1；全程未创新高 → 回撤 = 总收益
        self.assertAlmostEqual(r["total_return"], 0.99 ** 3 - 1.0, places=12)
        self.assertAlmostEqual(r["max_drawdown"], 0.99 ** 3 - 1.0, places=12)
        # 年化 = 0.99^252 - 1
        self.assertAlmostEqual(r["annual_return"], 0.99 ** 252 - 1.0, places=12)
        # calmar = (0.99^252 - 1) / |0.99^3 - 1|
        self.assertAlmostEqual(
            r["calmar"], (0.99 ** 252 - 1.0) / abs(0.99 ** 3 - 1.0), places=12
        )


class TradeMetricsTest(unittest.TestCase):
    """胜率/盈亏比/换手/持仓天数等交易侧指标（手算值）。"""

    def _trade(self, pnl: float, reason: str = "signal",
               entry_price: float = 10.0, exit_price: float = 11.0,
               shares: float = 100.0, hold_days: int = 5) -> Trade:
        return Trade(
            symbol="AAPL",
            entry_date=date(2025, 1, 2),
            exit_date=date(2025, 1, 2) + timedelta(days=hold_days),
            entry_price=entry_price,
            exit_price=exit_price,
            shares=shares,
            pnl=pnl,
            ret=pnl / (entry_price * shares),
            exit_reason=reason,
        )

    def test_win_rate_and_pl_ratio(self) -> None:
        trades = [
            self._trade(200.0),
            self._trade(100.0),
            self._trade(-50.0, reason="stop_loss"),
        ]
        r = stats.compute(_make_result([100.0, 101.0, 102.0], trades))
        # 胜率：pnl>0 计胜 → 2/3；盈亏比 = 平均盈利150 / 平均亏损50 = 3
        self.assertAlmostEqual(r["win_rate"], 2.0 / 3.0, places=12)
        self.assertAlmostEqual(r["profit_loss_ratio"], 3.0, places=12)
        self.assertEqual(r["trades"], 3)
        self.assertAlmostEqual(r["avg_hold_days"], 5.0, places=12)
        # 换手：Σ shares×(entry+exit) / 平均净值 = 3×100×21 / 101
        self.assertAlmostEqual(r["turnover"], 3 * 100 * 21.0 / 101.0, places=12)

    def test_exit_stats_breakdown(self) -> None:
        trades = [
            self._trade(100.0, reason="signal"),
            self._trade(-30.0, reason="signal"),
            self._trade(-50.0, reason="stop_loss"),
        ]
        r = stats.compute(_make_result([100.0, 101.0, 102.0], trades))
        sig = r["exit_stats"]["signal"]
        self.assertEqual(sig["count"], 2)
        self.assertAlmostEqual(sig["win_rate"], 0.5, places=12)
        self.assertAlmostEqual(sig["total_pnl"], 70.0, places=12)
        self.assertAlmostEqual(sig["avg_pnl"], 35.0, places=12)
        sl = r["exit_stats"]["stop_loss"]
        self.assertEqual(sl["count"], 1)
        self.assertAlmostEqual(sl["win_rate"], 0.0, places=12)


class DegradationTest(unittest.TestCase):
    """降级路径：净值不足两点 / 零波动时不崩，返回全零骨架或降级值。"""

    def test_empty_equity(self) -> None:
        r = stats.compute(_make_result([]))
        self.assertEqual(r["sharpe"], 0.0)
        self.assertEqual(r["days"], 0)

    def test_single_point(self) -> None:
        r = stats.compute(_make_result([100.0]))
        self.assertEqual(r["annual_return"], 0.0)
        self.assertEqual(r["days"], 1)

    def test_zero_volatility_sharpe_is_zero(self) -> None:
        # 恒定净值：收益全 0，标准差为 0 → 夏普降级 0 而不是 NaN/inf
        r = stats.compute(_make_result([100.0, 100.0, 100.0]))
        self.assertEqual(r["sharpe"], 0.0)
        self.assertEqual(r["annual_volatility"], 0.0)

    def test_all_positive_returns_sortino_zero(self) -> None:
        # 无负收益样本 → downside_std=0 → sortino 降级 0
        r = stats.compute(_make_result([100.0, 101.0, 102.01]))
        self.assertEqual(r["sortino"], 0.0)

    def test_risk_free_rate_annotation(self) -> None:
        # 口径标注字段必须存在且为 0（夏普按无风险利率 0 计算）
        r = stats.compute(_make_result([100.0, 101.0]))
        self.assertIn("risk_free_rate", r)
        self.assertEqual(r["risk_free_rate"], 0.0)


if __name__ == "__main__":
    unittest.main()
