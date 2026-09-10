"""mining 核心算法的回归测试（阶段 I1 嵌套折防泄漏 + I2 统计检验验收点固化）。

覆盖点（plans/TASKS-QUANT-BACKTEST.md 阶段 I review 记录）：
- I1 make_nested_folds：嵌套折结构（内层折全在外层训练段内）、purge 隔离带
  （test_start - train_end = purge_bars，forward return 窗口不跨边界）、
  embargo 禁区、天数不足优雅降级返回空、内层折 <2 的外层折降级跳过。
- I1 forward_returns：未来 h 日收益只出现在标签位，末尾 h 行 NaN；
  purge < horizon 的反例证明隔离带必要（隔离带 >= horizon 时训练段标签不跨界）。
- I2 统计函数黄金值：newey_west_t / bh_fdr_qvalues / deflated_sharpe_psr 手算对拍；
  性质断言：NW t 惩罚自相关（|NW t| < |naive t|）、BH q 单调递增。
"""
from __future__ import annotations

import math
import unittest

import numpy as np

from app.mining.core import NestedValidationConfig, forward_returns, make_nested_folds
from app.mining.stats import (
    bh_fdr_qvalues,
    deflated_sharpe_psr,
    expected_max_sharpe,
    naive_t,
    newey_west_t,
    normal_two_sided_p,
)


class NestedFoldsStructureTest(unittest.TestCase):
    """I1：嵌套折结构（小尺寸参数便于手算下标）。"""

    def _config(self) -> NestedValidationConfig:
        # 小参数：外层 20 训练 + 3 purge + 5 测试 + 1 embargo；内层 10 训练 + 3 测试；
        # 步进外层 5 / 内层 3；min_train 10
        return NestedValidationConfig(
            outer_train_bars=20,
            outer_test_bars=5,
            outer_step_bars=5,
            inner_train_bars=10,
            inner_test_bars=3,
            inner_step_bars=1,
            purge_bars=3,
            embargo_bars=1,
            min_train_bars=10,
        )

    def test_structure_indices_hand_calc(self) -> None:
        cfg = self._config()
        folds = make_nested_folds(28, cfg)
        self.assertEqual(len(folds), 1)  # 外层 required=28，仅一折
        outer = folds[0].outer
        # 手算下标：train [0,20)，purge 3，test [23,28)，embargo [28,29) 截到 n_days
        self.assertEqual((outer.train_start, outer.train_end), (0, 20))
        self.assertEqual((outer.test_start, outer.test_end), (23, 28))
        self.assertEqual(outer.embargo_end, 29)  # hard_stop 仅对内层生效
        self.assertEqual(outer.test_start - outer.train_end, cfg.purge_bars)

    def test_inner_folds_inside_outer_train(self) -> None:
        cfg = self._config()
        # 内层有效边界 = outer_train_stop - purge = 17；required 内层 = 10+3+3=16
        # → 折起点 0、1 满足（step=1），起点 2 不满足 → 2 个内层折
        folds = make_nested_folds(28, cfg)
        self.assertGreaterEqual(len(folds), 1)
        for nf in folds:
            self.assertGreaterEqual(len(nf.inner), 2)  # 单内层折的外层折降级跳过
            for f in nf.inner:
                self.assertEqual(f.level, "inner")
                # 内层折完全在外层训练段内（含前置隔离带：embargo_end <= 内层有效边界）
                self.assertGreaterEqual(f.train_start, nf.outer.train_start)
                # embargo_end 封顶于内层有效边界（hard_stop = outer_train_end - purge）
                self.assertLessEqual(f.embargo_end, nf.outer.train_end - 3)
                self.assertEqual(f.test_start - f.train_end, 3)  # purge 隔离带
                # embargo 禁区至少延伸测试段终点之后（封顶折可为 0，不短于 0）
                self.assertGreaterEqual(f.embargo_end, f.test_end)

    def test_purge_gap_equals_purge_bars(self) -> None:
        cfg = self._config()
        folds = make_nested_folds(28, cfg)
        for nf in folds:
            self.assertEqual(nf.outer.test_start - nf.outer.train_end, cfg.purge_bars)

    def test_insufficient_days_returns_empty(self) -> None:
        cfg = self._config()
        # 外层 required=28，27 天不够 → 空列表（优雅降级，不抛错）
        self.assertEqual(make_nested_folds(27, cfg), [])

    def test_config_validation_rejects_bad_values(self) -> None:
        with self.assertRaises(ValueError):
            NestedValidationConfig(outer_train_bars=100, min_train_bars=126)
        with self.assertRaises(ValueError):
            NestedValidationConfig(purge_bars=-1)


class ForwardReturnsLeakTest(unittest.TestCase):
    """I1：forward return 只在标签位，purge 隔离带防跨边界。"""

    def test_forward_returns_tail_nan_and_hand_calc(self) -> None:
        close = np.array([[10.0], [11.0], [12.0], [13.2]])
        fwd = forward_returns(close, horizon=2)
        # close[0]→close[2]: 12/10-1 = 0.2；close[1]→close[3]: 13.2/11-1 = 0.2
        self.assertAlmostEqual(fwd[0, 0], 0.2, places=12)
        self.assertAlmostEqual(fwd[1, 0], 0.2, places=12)
        # 末尾 h=2 行无未来数据 → NaN（标签位不外推）
        self.assertTrue(np.isnan(fwd[2:, 0]).all())

    def test_purge_gap_blocks_label_crossing(self) -> None:
        # 训练段 [0, train_end)，测试段自 test_start 起；horizon=3 的标签窗
        # 从训练末日 train_end-1 向后看 3 行到 train_end+2——
        # purge=3（>= horizon）时恰好在测试段起点之前截断，不跨界
        train_end, horizon, purge = 10, 3, 3
        test_start = train_end + purge
        last_label_end = (train_end - 1) + horizon  # 训练最后样本标签窗末行
        self.assertLess(last_label_end, test_start)  # 隔离带 >= horizon → 不跨边界
        # 反例：purge=2 < horizon=3 时标签窗跨入测试段（证明隔离带必要）
        test_start_bad = train_end + 2
        self.assertGreaterEqual(last_label_end, test_start_bad)


class StatsGoldenTest(unittest.TestCase):
    """I2：统计函数黄金值与性质断言（手算参考值，零第三方依赖）。"""

    def test_newey_west_t_hand_calc(self) -> None:
        # 无自相关序列 [1, -1, 1, -1, 1]：均值 0.2，lag=1 时
        # gamma0 = mean(x²) - mean² = 0.84...（逐步按定义手算展开对拍）
        x = np.array([1.0, -1.0, 1.0, -1.0, 1.0])
        n = 5
        mean = x.mean()
        centered = x - mean
        g0 = float(np.dot(centered, centered) / n)
        g1 = float(np.dot(centered[:-1], centered[1:]) / n)
        w1 = 1.0 - 1.0 / 2  # Bartlett 权重，lag=1
        long_var = g0 + 2 * w1 * g1
        expected_se = math.sqrt(max(long_var, 0.0) / n)
        expected_t = mean / expected_se
        out = newey_west_t(x.tolist(), lag=1)
        self.assertIsNotNone(out)
        t, m, se = out
        self.assertAlmostEqual(m, 0.2, places=12)
        self.assertAlmostEqual(se, expected_se, places=12)
        self.assertAlmostEqual(t, expected_t, places=12)

    def test_nw_penalizes_autocorrelation(self) -> None:
        # 强正自相关序列（验收记录性质断言：|NW t| < |naive t|）
        rng = np.random.default_rng(7)
        base = rng.normal(0.05, 1.0, 200)
        x = base + 0.8 * np.concatenate([[0.0], base[:-1]]) + 0.3
        nw = newey_west_t(x.tolist(), lag=5)
        nt = naive_t(x.tolist())
        self.assertIsNotNone(nw)
        self.assertIsNotNone(nt)
        self.assertLess(abs(nw[0]), abs(nt))

    def test_degenerate_inputs_return_none(self) -> None:
        self.assertIsNone(newey_west_t([1.0, 2.0], lag=1))  # 样本不足
        self.assertIsNone(newey_west_t([3.0] * 10, lag=1))  # 零方差
        self.assertIsNone(naive_t([1.0, 1.0, 1.0]))  # 零标准差

    def test_bh_fdr_qvalues_hand_calc(self) -> None:
        # p = [0.01, 0.04, 0.03]（m=3）：
        # rank1: 0.01*3/1=0.03；rank2: 0.03*3/2=0.045；rank3: 0.04*3/3=0.04
        # 从大到小单调回填：q(rank3)=0.04、q(rank2)=min(0.045,0.04)=0.04、q(rank1)=min(0.03,0.04)=0.03
        q = bh_fdr_qvalues([0.01, 0.04, 0.03])
        self.assertEqual(len(q), 3)
        self.assertAlmostEqual(q[0], 0.03, places=12)
        self.assertAlmostEqual(q[1], 0.04, places=12)
        self.assertAlmostEqual(q[2], 0.04, places=12)
        # 单调性：q 按 p 排序后单调不减
        ordered = [q[i] for i in np.argsort([0.01, 0.04, 0.03])]
        self.assertLessEqual(ordered[0], ordered[1])
        self.assertLessEqual(ordered[1], ordered[2])

    def test_bh_fdr_none_passthrough(self) -> None:
        q = bh_fdr_qvalues([0.05, None, 0.01])
        self.assertIsNone(q[1])
        self.assertEqual(len(q), 3)

    def test_normal_two_sided_p_golden(self) -> None:
        # t=1.96 → p ≈ 0.04999579（erfc 手算参考）；t=0 → p=1
        self.assertAlmostEqual(normal_two_sided_p(1.959963984540054), 0.05, places=6)
        self.assertAlmostEqual(normal_two_sided_p(0.0), 1.0, places=12)

    def test_deflated_sharpe_psr_hand_calc(self) -> None:
        # sharpe=0.5, n=100，无偏斜正态峰度、EM=0：
        # denominator = 1 + (3-1)/4×0.25 = 1.125；statistic = 0.5×√99/√1.125
        stat = 0.5 * math.sqrt(99) / math.sqrt(1.125)
        expected = 0.5 * (1.0 + math.erf(stat / math.sqrt(2.0)))
        out = deflated_sharpe_psr(0.5, 100)
        self.assertIsNotNone(out)
        self.assertAlmostEqual(out, expected, places=12)
        # 退化：n_obs < 5 → None
        self.assertIsNone(deflated_sharpe_psr(0.5, 4))

    def test_expected_max_sharpe_single_trial(self) -> None:
        self.assertEqual(expected_max_sharpe(1, 0.5), 0.0)
        # N 次试验 EM > 0 且随 N 增大
        self.assertGreater(expected_max_sharpe(10, 0.5), 0.0)
        self.assertGreater(expected_max_sharpe(100, 0.5), expected_max_sharpe(10, 0.5))


if __name__ == "__main__":
    unittest.main()
