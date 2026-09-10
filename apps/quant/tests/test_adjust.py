"""engine.adjust.forward_adjust 的回归测试（阶段 B/G1 复权验收点固化）。

覆盖点（plans/TASKS-QUANT-BACKTEST.md 阶段 G review 记录 + 代码口径）：
- 前复权价 = 原始价 × factor[t] / factor[T_last]（历史价向最新价看齐，最新价 = 原始价）。
- 除权日无跳空：10 送 10（因子 1→2）时复权收盘序列连续（当日复权收盘 = 前日复权收盘
  × 日收益，无除权造成的 50% 假跳空）。
- OHLC 同乘比例（K 线形态保持）、volume 反除（成交金额不变）、amount 不动。
- 无因子的标的原样返回 + flags 标注 False（优雅降级，报告标注未复权）。
- 与 data-api qfq 口径一致：因子序列最末日归一基准 = 1.0（验收记录：600519.SH 最新日
  qfq=1.0，引擎复权价与 /api/bars?adjust=qfq 逐分一致）。本测试用合成因子表同口径对拍，
  不依赖真实 data-api。
"""
from __future__ import annotations

import unittest
from datetime import date, timedelta

import numpy as np
import polars as pl

from app.engine.adjust import forward_adjust
from app.matrix import MarketMatrix

D0 = date(2026, 1, 5)
DATES = [D0 + timedelta(days=i) for i in range(4)]  # 4 个交易日


def _matrix(symbols: list[str], close_cols: list[list[float]]) -> MarketMatrix:
    """按收盘价列合成单标的市场矩阵（OHLC=close、volume=1e6、amount=close×1e6）。"""
    n = len(close_cols[0])
    close = np.array(close_cols, dtype=np.float64).T  # (dates × symbols)
    return MarketMatrix(
        dates=DATES[:n],
        symbols=list(symbols),
        open=close.copy(),
        high=close.copy(),
        low=close.copy(),
        close=close.copy(),
        volume=np.full(close.shape, 1e6),
        amount=close * 1e6,
    )


class ForwardAdjustTest(unittest.TestCase):
    """10 送 10（除权日因子 1→2）的前复权手算值。"""

    def setUp(self) -> None:
        # 除权日 = 第 3 天（index 2）：原始收盘 20, 20, 10（除权对半）, 11
        self.m = _matrix(["600519.SH"], [[20.0, 20.0, 10.0, 11.0]])
        self.factors = {
            "600519.SH": pl.DataFrame(
                {
                    "date": [DATES[0], DATES[2]],
                    "ex_factor": [1.0, 2.0],
                }
            )
        }

    def test_hand_calc_qfq_values(self) -> None:
        adj, flags = forward_adjust(self.m, self.factors)
        # T_last 因子 = 2 → 复权收盘 = 原始 × factor/2 = [10, 10, 10, 11]（手算）
        self.assertTrue(flags["600519.SH"])
        expected = np.array([10.0, 10.0, 10.0, 11.0])
        np.testing.assert_allclose(adj.close[:, 0], expected, rtol=0, atol=1e-12)

    def test_no_gap_on_ex_date(self) -> None:
        adj, _ = forward_adjust(self.m, self.factors)
        # 除权日（index 2）复权价无跳空：当日复权收盘 = 前日复权收盘（原始价腰斩被因子抵消）
        self.assertAlmostEqual(adj.close[2, 0], adj.close[1, 0], places=12)
        # 日收益链：复权收益率 = 原始价的「真」收益（0% / 0% / +10%）
        rets = adj.close[1:, 0] / adj.close[:-1, 0] - 1.0
        np.testing.assert_allclose(rets, [0.0, 0.0, 0.1], rtol=0, atol=1e-12)

    def test_last_day_factor_normalized_to_one(self) -> None:
        adj, _ = forward_adjust(self.m, self.factors)
        # data-api qfq 口径：因子序列最末日归一 = 1.0 → 最新复权价 = 最新原始价
        series = np.array([1.0, 1.0, 2.0, 2.0])  # _factor_series 的对齐结果
        normalized = series / series[-1]
        self.assertAlmostEqual(normalized[-1], 1.0, places=12)
        self.assertAlmostEqual(adj.close[-1, 0], self.m.close[-1, 0], places=12)

    def test_ohlc_scaled_volume_inverse_amount_unchanged(self) -> None:
        adj, _ = forward_adjust(self.m, self.factors)
        # OHLC 同乘比例：除权前（index 0）比例为 1/2
        self.assertAlmostEqual(adj.open[0, 0], self.m.open[0, 0] * 0.5, places=12)
        self.assertAlmostEqual(adj.high[0, 0], self.m.high[0, 0] * 0.5, places=12)
        self.assertAlmostEqual(adj.low[0, 0], self.m.low[0, 0] * 0.5, places=12)
        # volume 反除：除权前 ×2（成交金额不变）；amount 不动
        self.assertAlmostEqual(adj.volume[0, 0], self.m.volume[0, 0] * 2.0, places=6)
        np.testing.assert_allclose(adj.amount, self.m.amount, rtol=0, atol=0)
        # 复权后 price×volume 乘积不变（成交额守恒）
        np.testing.assert_allclose(
            adj.close * adj.volume, self.m.close * self.m.volume, rtol=1e-12, atol=0
        )

    def test_no_factor_passthrough_with_flag(self) -> None:
        # 标的缺因子表 → 原样返回 + flags=False（降级标注）
        m = _matrix(["AAPL"], [[100.0, 101.0, 102.0, 103.0]])
        adj, flags = forward_adjust(m, {"AAPL": pl.DataFrame({"date": [], "ex_factor": []})})
        self.assertFalse(flags["AAPL"])
        np.testing.assert_allclose(adj.close, m.close, rtol=0, atol=0)
        np.testing.assert_allclose(adj.volume, m.volume, rtol=0, atol=0)

    def test_mixed_symbols_flags(self) -> None:
        m = _matrix(
            ["600519.SH", "AAPL"],
            [[20.0, 20.0, 10.0, 11.0], [100.0, 100.0, 100.0, 100.0]],
        )
        adj, flags = forward_adjust(m, self.factors)
        self.assertTrue(flags["600519.SH"])
        self.assertFalse(flags["AAPL"])
        # 有因子列复权、无因子列原样，两列互不污染
        np.testing.assert_allclose(adj.close[:, 1], m.close[:, 1], rtol=0, atol=0)
        self.assertAlmostEqual(adj.close[0, 0], 10.0, places=12)


if __name__ == "__main__":
    unittest.main()
