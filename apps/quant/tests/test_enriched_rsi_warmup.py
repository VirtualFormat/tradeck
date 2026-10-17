"""enriched._rsi 新股预热口径回归测试（review 缺陷 4）。

旧实现按全局行号强置前 n 行 NaN：上市新股列前段全 NaN 时，首个有效 delta
出现在第 k>n 行，行号截断会让 RSI 在平滑不足 n 期时就提前出数。
修复后按每列首个有效收盘价起算：首个有效行 f 之后需 n 个 delta
（即 f+1 .. f+n 共 n-1 期平滑），第 f+n 行才允许出数。
"""
from __future__ import annotations

import unittest

import numpy as np

from app.matrix.enriched import _rsi

N = 14  # RSI 窗口


def _col(values: list[float], total_rows: int) -> np.ndarray:
    """构造一列：前段 NaN（模拟新股上市前），后段为给定收盘价。"""
    col = np.full(total_rows, np.nan)
    col[total_rows - len(values):] = values
    return col


class RsiWarmupNewListingTest(unittest.TestCase):
    def test_normal_column_warmup_unchanged(self) -> None:
        """全程有效列：预热行为与旧口径一致——前 n 行 NaN，第 n 行起出数。"""
        close = np.linspace(100, 130, 40)[:, None] + np.sin(np.arange(40))[:, None]
        rsi = _rsi(close, N)
        self.assertTrue(np.isnan(rsi[:N, 0]).all())
        self.assertTrue(np.isfinite(rsi[N:, 0]).all())

    def test_new_listing_warmup_from_first_valid(self) -> None:
        """新股列（前 5 行 NaN）：行号口径下第 14 行就出数（只有 8 期平滑），
        新口径须到第 first_valid+n = 19 行才允许出数。"""
        close = np.empty((40, 1))
        close[:, 0] = np.nan
        close[5:, 0] = np.linspace(50, 70, 35) + np.sin(np.arange(35))
        rsi = _rsi(close, N)
        # 第 14~18 行旧口径会出数，新口径仍为 NaN（平滑不足）
        self.assertTrue(np.isnan(rsi[5:5 + N, 0]).all())
        # 第 19 行起出数（恰累计 14 个 delta / 13 期平滑后的第一期）
        self.assertTrue(np.isfinite(rsi[5 + N:, 0]).all())

    def test_all_nan_column_stays_nan(self) -> None:
        """全 NaN 列（无缓存标的）：整列保持 NaN，不抛错。"""
        close = np.full((30, 1), np.nan)
        rsi = _rsi(close, N)
        self.assertTrue(np.isnan(rsi).all())

    def test_suspension_gap_mid_column(self) -> None:
        """中部停牌缺口的列不受影响：首个有效点仍在行 0，预热照常 n 行。"""
        close = np.linspace(100, 130, 40) + np.sin(np.arange(40))
        close[10:13] = np.nan  # 行 10~12 停牌
        rsi = _rsi(close[:, None], N)
        self.assertTrue(np.isnan(rsi[:N, 0]).all())
        # 停牌处 delta 为 NaN 会打断递推，但预热截断仍以行 0 起算
        self.assertTrue(np.isfinite(rsi[N, 0]))

    def test_rows_shorter_than_warmup(self) -> None:
        """总行数 <= 首个有效行 + n 时整列 NaN（样本不足以完成预热）。"""
        close = np.empty((10, 1))
        close[:, 0] = np.nan
        close[3:, 0] = np.linspace(50, 55, 7)
        rsi = _rsi(close, N)
        self.assertTrue(np.isnan(rsi).all())


if __name__ == "__main__":
    unittest.main()
