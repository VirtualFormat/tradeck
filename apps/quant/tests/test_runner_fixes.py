"""缺陷 3 / 缺陷 4 修复验收：runner._fetch_benchmark 对齐 + 优化网格上限前置校验。

缺陷 3：基准指数 rows 里 close=None 的行曾只从 closes 剔除、dates 全保留，
zip 按位置配对时空洞之后的 close 整体前移一天静默错配。修复后 date/close
一起过滤，结果 dates 与 closes 严格一一对应。

缺陷 4：validate_optimize_request 曾只调 count_combinations 不查
GRID_MAX_COMBINATIONS，超限网格先跑分钟级全市场暖缓存才被
expand_param_grid 拒（422 迟到）。修复后前置校验直接拒绝超限网格。

runner 依赖 polars，本机缺依赖时整体 skip（与仓库存量测试的
skipUnless 风格一致，devcontainer 内全量跑）。
"""
from __future__ import annotations

import asyncio
import unittest
from datetime import date
from unittest import mock

try:
    import polars  # noqa: F401

    _HAS_DEPS = True
except ModuleNotFoundError:  # 本机无 polars：skip，不阻塞宿主环境
    _HAS_DEPS = False


@unittest.skipUnless(_HAS_DEPS, "缺 polars（devcontainer 内跑）")
class FetchBenchmarkAlignmentTest(unittest.TestCase):
    """_fetch_benchmark：close=None 行连 date 一起剔除，dates/closes 不错位。"""

    def _run_fetch(self, rows: list[dict]) -> dict | None:
        from app import runner

        async def go():
            with mock.patch.object(
                runner.client, "get_json", new=mock.AsyncMock(return_value=rows)
            ):
                return await runner._fetch_benchmark(
                    ["AAPL"], date(2026, 1, 1), date(2026, 1, 10)
                )

        return asyncio.run(go())

    def test_none_close_row_removed_with_its_date(self) -> None:
        """中间一行 close=None：date 一并剔除，不出现整体前移一天的静默错配。"""
        rows = [
            {"date": "2026-01-05", "close": 100.0},
            {"date": "2026-01-06", "close": None},   # 空洞行
            {"date": "2026-01-07", "close": 102.0},
            {"date": "2026-01-08", "close": 103.0},
        ]
        result = self._run_fetch(rows)
        self.assertIsNotNone(result)
        # 修复前：dates 保留 4 天，closes 只有 3 个 → 1-07 配 103、1-08 越界静默错
        self.assertEqual(result["dates"], ["2026-01-05", "2026-01-07", "2026-01-08"])
        self.assertEqual(result["closes"], [100.0, 102.0, 103.0])
        self.assertEqual(len(result["dates"]), len(result["closes"]))

    def test_all_none_close_returns_none(self) -> None:
        """全部 close=None → 降级 None（与旧语义一致，不阻塞回测）。"""
        rows = [
            {"date": "2026-01-05", "close": None},
            {"date": "2026-01-06", "close": None},
        ]
        self.assertIsNone(self._run_fetch(rows))

    def test_normal_rows_unchanged(self) -> None:
        """无空洞的正常响应结果不变（回归保护）。"""
        rows = [
            {"date": "2026-01-06", "close": 102.0},
            {"date": "2026-01-05", "close": 100.0},  # 乱序：函数内按日期排序
        ]
        result = self._run_fetch(rows)
        self.assertEqual(result["dates"], ["2026-01-05", "2026-01-06"])
        self.assertEqual(result["closes"], [100.0, 102.0])
        self.assertAlmostEqual(result["total_return"], 0.02)


@unittest.skipUnless(_HAS_DEPS, "缺 polars（devcontainer 内跑）")
class ValidateOptimizeLimitTest(unittest.TestCase):
    """validate_optimize_request：超限网格在暖缓存前 fail fast。"""

    def _registry(self, params_schema: list[dict]):
        """最小桩 registry：只实现 validate 路径用到的 get().params_schema /
        is_minute_strategy（不扫目录、不加载真实策略文件）。"""
        strategy = mock.Mock()
        strategy.is_minute_strategy = False
        strategy.params_schema = params_schema
        registry = mock.Mock()
        registry.get.return_value = strategy
        return registry

    def test_over_limit_grid_rejected_upfront(self) -> None:
        from app import runner
        from app.engine import optimizer

        # 单参数 0~100 step 0.01 → 10001 个候选，远超 GRID_MAX_COMBINATIONS
        registry = self._registry(
            [{"id": "x", "type": "float", "min": 0, "max": 100, "step": 0.01}]
        )
        grid = {"x": {"min": 0, "max": 100, "step": 0.01}}
        total = optimizer.count_combinations(
            registry.get("s").params_schema, grid
        )
        self.assertGreater(total, optimizer.GRID_MAX_COMBINATIONS)  # 前提确认

        with self.assertRaises(ValueError) as ctx:
            runner.validate_optimize_request(registry, "s", grid)
        self.assertIn("超过上限", str(ctx.exception))
        self.assertIn(str(optimizer.GRID_MAX_COMBINATIONS), str(ctx.exception))

    def test_within_limit_grid_passes(self) -> None:
        """未超限网格正常通过（回归保护：不误伤合法请求）。"""
        from app import runner

        registry = self._registry(
            [{"id": "x", "type": "int", "min": 1, "max": 10, "step": 1}]
        )
        # 10 个候选，远低于上限 —— 不抛错即通过
        runner.validate_optimize_request(registry, "s", {"x": [1, 5, 10]})
        runner.validate_optimize_request(
            registry, "s", {"x": {"min": 1, "max": 10, "step": 1}}
        )

    def test_limit_check_uses_same_threshold_as_engine(self) -> None:
        """边界：组合数恰好等于 GRID_MAX_COMBINATIONS 时通过（与
        expand_param_grid 的 > 判定同阈值，两边口径一致）。"""
        from app import runner
        from app.engine import optimizer

        n = optimizer.GRID_MAX_COMBINATIONS  # 恰好 2000 个候选
        registry = self._registry(
            [{"id": "x", "type": "int", "min": 0, "max": n}]
        )
        # values 列表 0..n-1 恰好 n 个，不越界（pmeta.max=n 兜底）
        runner.validate_optimize_request(
            registry, "s", {"x": list(range(n))}
        )


if __name__ == "__main__":
    unittest.main()
