"""统计黄金向量随迁测试 — 锁定 mining/stats.py 与参照实现数值口径一致。

黄金参考向量直接迁自参照仓库 tick-stock-panel
backend/tests/test_stats_v2.py（其断言值由该测试内独立第二实现推导）：
- NW HAC t：参照用显式循环按定义求 Bartlett 加权长方差作为第二实现对拍，
  本文件同样内联该第二实现，逐位对拍向量化实现（rel < 1e-9）。
- BH-FDR q：经典 BH 示例（Wikipedia）黄金值 + 乱序回填黄金值。
- DSR/PSR：无偏斜无超额峰度时退化为 Φ(SR*sqrt(n-1)) 的解析黄金值。

签名差异说明：参照 deflated_sharpe_psr(sharpe, n_obs, skewness, kurtosis,
expected_max_sharpe) 与 quant 版主口径公式完全一致
（分母 1 - skew*SR + (kurt-1)/4*SR^2），quant 版仅多出可选的
n_trials/variance_sharpes 便捷参数（不传时行为与参照逐位一致），
故 DSR 黄金向量直接适用，无需手算改值。
"""
from __future__ import annotations

import math
import unittest

import numpy as np

from app.mining.stats import (
    bh_fdr_qvalues,
    deflated_sharpe_psr,
    newey_west_t,
)


def _nw_t_reference(values: list[float], lag: int) -> float | None:
    """独立第二实现：显式循环按定义计算 Bartlett 核 HAC t 值（照搬参照测试）。"""
    n = len(values)
    if n <= lag + 1:
        return None
    mean = sum(values) / n
    centered = [value - mean for value in values]
    gamma = [
        sum(centered[i] * centered[i + lag_i] for i in range(n - lag_i)) / n
        for lag_i in range(lag + 1)
    ]
    long_var = gamma[0]
    for lag_i in range(1, lag + 1):
        long_var += 2.0 * (1.0 - lag_i / (lag + 1)) * gamma[lag_i]
    if long_var <= 0:
        return None
    se = math.sqrt(long_var / n)
    return mean / se


class NeweyWestGoldenTest(unittest.TestCase):
    """NW HAC t 值黄金向量：与参照第二实现逐位对拍。"""

    def test_matches_reference_implementation(self) -> None:
        rng = np.random.default_rng(42)
        values = np.cumsum(rng.normal(0, 0.01, 60)).tolist()  # 高自相关
        for lag in (1, 3, 5):
            result = newey_west_t(values, lag)
            self.assertIsNotNone(result)
            t_stat, mean, se = result
            reference = _nw_t_reference(values, lag)
            self.assertIsNotNone(reference)
            self.assertAlmostEqual(t_stat, reference, delta=abs(reference) * 1e-9)
            self.assertAlmostEqual(mean, float(np.mean(values)), places=15)
            self.assertGreater(se, 0)

    def test_deflates_autocorrelated_t(self) -> None:
        # 强正自相关序列：NW t 的绝对值必须小于朴素 t（自相关被正确惩罚）
        rng = np.random.default_rng(7)
        phi = 0.9
        values, last = [], 0.0
        for shock in rng.normal(0, 0.01, 500):
            last = phi * last + shock
            values.append(last)
        array = np.asarray(values)
        t_naive = float(array.mean()) / (float(array.std(ddof=1)) / math.sqrt(len(values)))
        result = newey_west_t(values, lag=5)
        self.assertIsNotNone(result)
        self.assertLess(abs(result[0]), abs(t_naive))

    def test_insufficient_samples(self) -> None:
        self.assertIsNone(newey_west_t([0.1, 0.2], lag=1))
        self.assertIsNone(newey_west_t([], lag=1))
        self.assertIsNone(newey_west_t([1.0] * 20, lag=1))  # 零方差


class BhFdrGoldenTest(unittest.TestCase):
    """BH-FDR q 值黄金向量（参照断言值直抄）。"""

    def test_classic_bh_example(self) -> None:
        # 经典 BH 示例（Wikipedia）：q = [.005, .02, .042, .042, .042]
        pvalues = [0.001, 0.008, 0.039, 0.041, 0.042]
        expected = [0.005, 0.02, 0.042, 0.042, 0.042]
        for actual, want in zip(bh_fdr_qvalues(pvalues), expected):
            self.assertAlmostEqual(actual, want, places=12)

    def test_unsorted_input_keeps_positions(self) -> None:
        # 乱序输入：q 值跟随原位置
        # （m=3：.042→r3 raw .042；.001→.003；.039→min(.0585,.042)=.042）
        expected = [0.042, 0.003, 0.042]
        for actual, want in zip(bh_fdr_qvalues([0.042, 0.001, 0.039]), expected):
            self.assertAlmostEqual(actual, want, places=12)

    def test_none_passthrough(self) -> None:
        self.assertEqual(bh_fdr_qvalues([None, 0.05]), [None, 0.05])


class DeflatedSharpeGoldenTest(unittest.TestCase):
    """DSR/PSR 黄金向量（参照断言值直抄；主口径公式与参照一致，见模块 docstring）。"""

    def test_degenerates_to_plain_psr(self) -> None:
        # 无偏斜无超额峰度时退化为 Φ(SR * sqrt(n-1))。
        # 容差放宽到 1e-6（对齐参照 pytest.approx 默认 rel=1e-6）：
        # quant 版把 -0.0 归零处理（(0.1-0.0) 而非参照的 0.1 直乘），
        # IEEE 浮点下二者差 ~2e-8，同值不同运算序，非口径差异。
        probability = deflated_sharpe_psr(
            sharpe=0.1, n_obs=2500, skewness=0.0, kurtosis=3.0, expected_max_sharpe=0.0
        )
        self.assertAlmostEqual(
            probability,
            0.5 * (1 + math.erf(0.1 * math.sqrt(2499) / math.sqrt(2))),
            delta=1e-6,
        )

    def test_penalty_lowers_psr(self) -> None:
        baseline = deflated_sharpe_psr(0.1, 2500, skewness=0.0, kurtosis=3.0)
        # 峰度校正项抬高分母会降低 PSR
        penalized = deflated_sharpe_psr(0.1, 2500, skewness=0.0, kurtosis=10.0)
        self.assertLess(penalized, baseline)
        # 期望最大夏普 EM 校正降低显著性
        deflated = deflated_sharpe_psr(0.1, 2500, 0.0, 3.0, expected_max_sharpe=0.08)
        self.assertLess(deflated, baseline)

    def test_insufficient_obs(self) -> None:
        self.assertIsNone(deflated_sharpe_psr(0.1, 3))  # 样本不足


if __name__ == "__main__":
    unittest.main()
