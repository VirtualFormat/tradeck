"""结果契约接线测试（阶段 L review P1-3）：run_backtest 返回 dict 与
FastAPI 任务化端点的结构断言，防「后端输出 A、前端消费 B」静默漂移。

两层覆盖：
1. run_backtest 端到端：合成日K 喂 ma_golden_cross，断言扩展字段存在且
   结构与前端 types.ts 消费口径一致（bucket_start/bucket_end、cumulative_pnl、
   selection_stats 三 key、per_symbol_stats.name）。
2. API 层：run → poll/cancel 路由存在、未知任务 404、cancel 幂等。
"""
from __future__ import annotations

import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

import polars as pl

from app.config import settings
from app.data import store

SYM = "AAPL"
_N = 45
_D0 = date(2026, 1, 5)

# 与 test_minute_refs 同款合成序列：平盘 → 反弹出金叉 → 回落出死叉，保证有成交
_CLOSES = (
    [10.0] * 20
    + [10.3, 10.6, 10.9, 11.2, 11.5]
    + [11.3, 11.0, 10.7]
    + [10.6] * 17
)


def _dates(n: int) -> list[date]:
    return [_D0 + timedelta(days=i) for i in range(n)]


def _run_backtest_once() -> dict:
    """合成数据跑一次日K 回测（独立临时缓存目录，跑完还原）。"""
    from app.engine import MatcherConfig
    from app.runner import run_backtest
    from app.strategy import StrategyRegistry
    from app.strategy import loader as strategy_loader

    old_cache = settings.QUANT_CACHE_DIR
    with tempfile.TemporaryDirectory() as tmp:
        settings.QUANT_CACHE_DIR = tmp
        try:
            store.save(SYM, pl.DataFrame({
                "symbol": [SYM] * _N,
                "date": _dates(_N),
                "open": _CLOSES[-1:] + _CLOSES[:-1],
                "high": [max(o, c) for o, c in zip(_CLOSES[-1:] + _CLOSES[:-1], _CLOSES)],
                "low": [min(o, c) for o, c in zip(_CLOSES[-1:] + _CLOSES[:-1], _CLOSES)],
                "close": _CLOSES,
                "volume": [1_000_000] * _N,
                "amount": [c * 1e6 for c in _CLOSES],
            }))
            registry = StrategyRegistry(
                {"builtin": Path(strategy_loader.__file__).parent / "builtin"}
            )
            return run_backtest(
                [SYM],
                "ma_golden_cross",
                _dates(_N)[0],
                _dates(_N)[-1],
                params={"require_above_ma60": False, "vol_ratio_min": 0.0},
                config=MatcherConfig(),
                registry=registry,
                names={SYM: "苹果"},
            )
        finally:
            settings.QUANT_CACHE_DIR = old_cache


class RunBacktestResultSchemaTest(unittest.TestCase):
    """run_backtest 返回 dict 的扩展字段接线断言（review P0-1 漂移的拦截层）。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.result = _run_backtest_once()

    def test_top_level_extension_keys(self) -> None:
        r = self.result
        for key in (
            "run_id", "elapsed_ms", "per_symbol_stats", "return_distribution",
            "daily_trade_rows", "selection_stats",
        ):
            self.assertIn(key, r, f"缺少扩展字段 {key}")
        self.assertIsInstance(r["run_id"], str)
        self.assertGreaterEqual(r["elapsed_ms"], 0)
        # 蒙卡回撤字段挂在 stats 上（交易日足够时应有值）
        self.assertIn("mc_maxdd_p50", r["stats"])
        self.assertIn("mc_maxdd_p95", r["stats"])

    def test_selection_stats_keys(self) -> None:
        sel = self.result["selection_stats"]
        self.assertEqual(
            set(sel), {"signals_entry", "signals_exit", "filled_trades"},
            "selection_stats 只产出如实三 key，前端中文映射依赖此集合",
        )
        self.assertGreater(sel["signals_entry"], 0)

    def test_return_distribution_bucket_shape(self) -> None:
        dist = self.result["return_distribution"]
        self.assertTrue(dist, "有成交时分布不应为空")
        for bucket in dist:
            # 前端染色/标签依赖数值区间字段（review P0-1 的漂移点）
            self.assertIn("bucket_start", bucket)
            self.assertIn("bucket_end", bucket)
            self.assertIn("count", bucket)
            self.assertLess(bucket["bucket_start"], bucket["bucket_end"])

    def test_daily_trade_rows_shape(self) -> None:
        rows = self.result["daily_trade_rows"]
        self.assertTrue(rows)
        for row in rows:
            self.assertEqual(
                set(row),
                {"date", "buys", "sells", "realized_pnl", "cumulative_pnl", "equity"},
            )
        # 累计盈亏单调等于末行 = 全部卖出日盈亏之和
        self.assertAlmostEqual(
            rows[-1]["cumulative_pnl"],
            round(sum(r["realized_pnl"] for r in rows), 2),
            places=2,
        )

    def test_per_symbol_stats_name_wiring(self) -> None:
        per = self.result["per_symbol_stats"]
        self.assertTrue(per, "有成交时分标的统计不应为空")
        self.assertEqual(per[0]["symbol"], SYM)
        # names dict 已在 runner 手里，name 键必须透出（前端名称列依赖）
        self.assertEqual(per[0]["name"], "苹果")


class BacktestTaskApiWiringTest(unittest.TestCase):
    """任务化端点接线：路由注册 + 未知任务 404 + cancel 幂等。

    说明：本仓库 starlette 版本的 TestClient 对「只挂了端点函数的干净 app」
    存在挂起问题（portal 兼容性），故直接调用端点函数断言行为——
    HTTP 层只剩 FastAPI 的异常转换，已由框架保证。
    """

    @classmethod
    def setUpClass(cls) -> None:
        from app.api import app

        cls.source_app = app

    def test_routes_registered(self) -> None:
        paths = {r.path for r in self.source_app.routes}
        for p in (
            "/api/backtest",
            "/api/backtest/run",
            "/api/backtest/task/{task_id}",
            "/api/backtest/task/{task_id}/cancel",
        ):
            self.assertIn(p, paths)

    def test_poll_unknown_task_404(self) -> None:
        from fastapi import HTTPException

        from app.api import api_backtest_task_poll

        with self.assertRaises(HTTPException) as ctx:
            api_backtest_task_poll("nonexistent-task-id")
        self.assertEqual(ctx.exception.status_code, 404)

    def test_cancel_unknown_task_404(self) -> None:
        from fastapi import HTTPException

        from app.api import api_backtest_task_cancel

        with self.assertRaises(HTTPException) as ctx:
            api_backtest_task_cancel("nonexistent-task-id")
        self.assertEqual(ctx.exception.status_code, 404)

    def test_poll_response_shape_for_pending(self) -> None:
        """直接注册一个 pending 任务验证轮询响应结构（不跑真回测，保持快）。"""
        from app.api import api_backtest_task_poll
        from app.tasks import get_registry as get_task_registry

        task = get_task_registry().create()
        body = api_backtest_task_poll(task.task_id)
        self.assertEqual(body["status"], "pending")
        self.assertNotIn("result", body)
        self.assertNotIn("error", body)

    def test_cancel_idempotent(self) -> None:
        """cancel 幂等：重复取消/对终态任务取消都返回现状不报错。"""
        from app.api import api_backtest_task_cancel
        from app.tasks import get_registry as get_task_registry

        task = get_task_registry().create()
        first = api_backtest_task_cancel(task.task_id)
        self.assertEqual(first["status"], "cancelled")
        second = api_backtest_task_cancel(task.task_id)
        self.assertEqual(second["status"], "cancelled")


if __name__ == "__main__":
    unittest.main()
