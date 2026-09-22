"""walkforward 折切分 purge 口径声明的回归测试（review 缺陷 3）。

折切分无 purge 隔离带（purge=0，训练窗末与测试窗首仅后移 1 个日历日防
同日重叠），与 mining 模块「purge_bars >= horizon」的交易日 embargo
铁律口径不同——该口径是注释锁定的有意选择，修复方向是显式声明：
- generate_folds docstring 明确标注无 purge；
- run_walk_forward 结果 dict 的 meta 字段透出 purge_bars/purge_note 供 UI 展示。
"""
from __future__ import annotations

import inspect
import unittest
from datetime import date

from app.engine.walkforward import (
    WalkForwardConfig,
    generate_folds,
    run_walk_forward,
)


def _fake_run_fn(symbols, strategy_id, start, end, params=None, config=None):
    """桩回测执行函数：固定返回一份有效 stats，让每折都成为有效折。"""
    return {"stats": {"total_return": 0.01, "sharpe": 1.0}}


class GenerateFoldsPurgeDocTest(unittest.TestCase):
    def test_docstring_declares_no_purge(self) -> None:
        """generate_folds docstring 须显式声明无 purge 口径（防口径漂移）。"""
        doc = inspect.getdoc(generate_folds) or ""
        self.assertIn("purge=0", doc)
        self.assertIn("无 purge", doc)
        self.assertIn("mining", doc)

    def test_fold_behavior_unchanged(self) -> None:
        """行为不变：test_start = train_end + 1 日历日（隔断同日重叠但无 embargo）。"""
        folds = generate_folds(
            date(2025, 1, 1), date(2025, 4, 30),
            train_days=60, test_days=20, step_days=20,
        )
        self.assertTrue(folds)
        for f in folds:
            self.assertEqual((f.test_start - f.train_end).days, 1)


class WalkForwardMetaTest(unittest.TestCase):
    def test_result_meta_declares_no_purge(self) -> None:
        """结果 dict 的 meta 透出 purge=0 口径说明，供 UI 展示。"""
        cfg = WalkForwardConfig(
            strategy_id="stub",
            symbols=["X"],
            start=date(2025, 1, 1),
            end=date(2025, 4, 30),
            param_grid={"p": [1, 2]},
            objective="sharpe",
            train_days=60,
            test_days=20,
            step_days=20,
        )
        # params_meta 让网格展开出 2 组参数（expand_param_grid 需要 params 元数据）
        params_meta = [{"id": "p", "default": 1}]
        result = run_walk_forward(cfg, params_meta, _fake_run_fn)

        self.assertIn("meta", result)
        self.assertEqual(result["meta"]["purge_bars"], 0)
        self.assertIn("无 purge", result["meta"]["purge_note"])
        self.assertIn("mining", result["meta"]["purge_note"])
        # 训练优化对桩 stats 无法算 IC（返回 None 被跳过），n_folds=0 也
        # 必须透出 meta（口径声明与有效折数无关）
        self.assertIn("n_planned_folds", result)


if __name__ == "__main__":
    unittest.main()
