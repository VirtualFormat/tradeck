"""优化/敏感性/walk-forward API 透出测试（阶段 M1）。

与 test_result_wiring 同款风格：直接调用端点协程函数断言行为（本仓库
starlette 版本的 TestClient 存在挂起问题）；真跑端到端用 mock 屏蔽网络
预拉（_fetch_benchmark/_fetch_names），进程内小网格走 run_backtest。
"""
from __future__ import annotations

import asyncio
import tempfile
import unittest
from datetime import date, timedelta
from unittest import mock
from unittest.mock import AsyncMock

import polars as pl

from app.config import settings
from app.data import store

SYM = "AAPL"
_N = 45
_D0 = date(2026, 1, 5)
_UID = "default"  # 直接调端点函数时显式传 user_id（绕过 FastAPI Depends 默认值）

# 与 test_result_wiring 同款合成序列：平盘 → 反弹出金叉 → 回落出死叉，保证有成交
_CLOSES = (
    [10.0] * 20
    + [10.3, 10.6, 10.9, 11.2, 11.5]
    + [11.3, 11.0, 10.7]
    + [10.6] * 17
)


def _dates(n: int) -> list[date]:
    return [_D0 + timedelta(days=i) for i in range(n)]


def _seed_cache(cache_dir: str) -> None:
    """把合成日K 灌进临时缓存目录（store 是唯一行情读口）。"""
    settings.QUANT_CACHE_DIR = cache_dir
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


def _optimize_request(**overrides):
    from app.api import OptimizeRequest

    payload = {
        "symbols": [SYM],
        "strategy_id": "ma_golden_cross",
        "start": _D0,
        "end": _dates(_N)[-1],
        "param_grid": {"vol_ratio_min": [0.0, 1.0]},
        "base_params": {"require_above_ma60": False},
    }
    payload.update(overrides)
    return OptimizeRequest(**payload)


def _no_network():
    """屏蔽 runner 预拉网络（基准/名称），返回两个 patcher 的上下文元组。"""
    return (
        mock.patch("app.runner._fetch_benchmark", new=AsyncMock(return_value=None)),
        mock.patch("app.runner._fetch_names", new=AsyncMock(return_value={})),
    )


class OptimizeApiRouteTest(unittest.TestCase):
    """端点注册存在（三路由挂载，改名漂移可拦截）。"""

    def test_routes_registered(self) -> None:
        from app.api import app

        paths = {r.path for r in app.routes}
        for p in ("/api/optimize", "/api/sensitivity", "/api/walkforward"):
            self.assertIn(p, paths)


class OptimizeApiErrorMappingTest(unittest.TestCase):
    """错误分层：非法 objective/grid → 422；universe 展开互斥语义；KeyError → 404。"""

    def test_invalid_objective_422(self) -> None:
        from fastapi import HTTPException

        from app.api import api_optimize

        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(api_optimize(_optimize_request(objective="not_an_objective"),
                                     user_id=_UID))
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertIn("not_an_objective", ctx.exception.detail)

    def test_invalid_grid_422(self) -> None:
        """grid 引用策略不存在的参数 → optimizer 的 ValueError 转 422。"""
        from fastapi import HTTPException

        from app.api import api_optimize

        req = _optimize_request(param_grid={"no_such_param": [1, 2]})
        p1, p2 = _no_network()
        with p1, p2:
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(api_optimize(req, user_id=_UID))
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertIn("no_such_param", ctx.exception.detail)

    def test_universe_default_expands_to_tracked(self) -> None:
        """symbols 缺省时按 universe 默认档 tracked 展开（runner 层 mock，保持快）。"""
        from app import runner as quant_runner
        from app.api import api_optimize
        from app.jobs import DEFAULT_SIGNAL_UNIVERSE

        req = _optimize_request(symbols=None)
        with mock.patch.object(
            quant_runner, "run_optimize", new=AsyncMock(return_value={"ok": True})
        ) as mocked:
            out = asyncio.run(api_optimize(req, user_id=_UID))
        self.assertEqual(out, {"ok": True})
        self.assertEqual(mocked.call_args.args[0], list(DEFAULT_SIGNAL_UNIVERSE))

    def test_explicit_symbols_win_over_universe(self) -> None:
        """显式 symbols 优先：universe 参数被忽略（互斥语义与 api_screen 一致）。"""
        from app import runner as quant_runner
        from app.api import api_optimize

        req = _optimize_request(symbols=[SYM], universe="cn")
        with mock.patch.object(
            quant_runner, "run_optimize", new=AsyncMock(return_value={"ok": True})
        ) as mocked:
            asyncio.run(api_optimize(req, user_id=_UID))
        self.assertEqual(mocked.call_args.args[0], [SYM])

    def test_unknown_strategy_404(self) -> None:
        """runner 侧 KeyError（策略不存在）→ 404。"""
        from fastapi import HTTPException

        from app import runner as quant_runner
        from app.api import api_optimize

        async def _raise(*a, **k):
            raise KeyError("策略不存在 'nope'")

        with mock.patch.object(quant_runner, "run_optimize", side_effect=_raise):
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(api_optimize(_optimize_request(), user_id=_UID))
        self.assertEqual(ctx.exception.status_code, 404)


class OptimizeApiEndToEndTest(unittest.TestCase):
    """极小网格真跑一次：结果结构含 best_params/results/rank（进程内串行路径）。"""

    @classmethod
    def setUpClass(cls) -> None:
        from app.api import api_optimize

        cls.old_cache = settings.QUANT_CACHE_DIR
        cls.tmp = tempfile.TemporaryDirectory()
        _seed_cache(cls.tmp.name)
        p1, _p2 = _no_network()
        with p1, mock.patch(
            "app.runner._fetch_names", new=AsyncMock(return_value={SYM: "苹果"})
        ):
            cls.result = asyncio.run(api_optimize(_optimize_request(), user_id=_UID))

    @classmethod
    def tearDownClass(cls) -> None:
        settings.QUANT_CACHE_DIR = cls.old_cache
        cls.tmp.cleanup()

    def test_top_level_shape(self) -> None:
        r = self.result
        for key in ("strategy", "symbols", "range", "objective", "direction",
                    "n_combinations", "n_completed", "n_errors",
                    "best_params", "best_score", "results", "elapsed_ms",
                    "execution"):
            self.assertIn(key, r, f"缺少字段 {key}")
        self.assertEqual(r["n_combinations"], 2)
        self.assertEqual(r["n_completed"], 2)
        self.assertEqual(r["n_errors"], 0)
        self.assertEqual(r["execution"], "inprocess")  # 2 组合低于派发阈值

    def test_results_ranked_with_rank_key(self) -> None:
        rows = self.result["results"]
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertIn("params", row)
            self.assertIn("objective_raw", row)
            self.assertIn("rank", row)
            # 响应瘦身（review P2-2）：stats 嵌套字典收敛为 4 个扁平键，
            # 对齐前端排名表列（types.ts OptimizeResultRow），原 stats 键删除
            for key in ("total_return", "sharpe", "max_drawdown", "trades"):
                self.assertIn(key, row)
            self.assertNotIn("stats", row)
        # rank 连续 1..n；sharpe 默认 max 方向降序
        self.assertEqual([r["rank"] for r in rows], [1, 2])
        self.assertGreaterEqual(rows[0]["objective_raw"], rows[1]["objective_raw"])

    def test_best_params_matches_rank1(self) -> None:
        r = self.result
        self.assertIsNotNone(r["best_params"])
        self.assertEqual(r["best_params"], r["results"][0]["params"])
        self.assertEqual(r["best_score"], round(r["results"][0]["objective_raw"], 4))


class WalkforwardApiEndToEndTest(unittest.TestCase):
    """walk-forward 端到端形状断言（阶段 M review P0-1/P0-2 的契约锁）：
    顶层 compounded_oos_return/degradation/consistency + 折记录扁平键
    oos_total_return/oos_sharpe——前端 types.ts 消费的单一形态，防漂移。
    """

    @classmethod
    def setUpClass(cls) -> None:
        from app.api import WalkForwardRequest, api_walkforward

        cls.old_cache = settings.QUANT_CACHE_DIR
        cls.tmp = tempfile.TemporaryDirectory()
        _seed_cache(cls.tmp.name)
        p1, _p2 = _no_network()
        req = WalkForwardRequest(
            symbols=[SYM],
            strategy_id="ma_golden_cross",
            start=_D0,
            end=_dates(_N)[-1],
            param_grid={"vol_ratio_min": [0.0, 1.0]},
            base_params={"require_above_ma60": False},
            train_days=20, test_days=10, step_days=10,
        )
        with p1, mock.patch(
            "app.runner._fetch_names", new=AsyncMock(return_value={SYM: "苹果"})
        ):
            cls.result = asyncio.run(api_walkforward(req, user_id=_UID))

    @classmethod
    def tearDownClass(cls) -> None:
        settings.QUANT_CACHE_DIR = cls.old_cache
        cls.tmp.cleanup()

    def test_top_level_flat_keys(self) -> None:
        """P0-1 锁：compounded_oos_return 在顶层（不在嵌套 summary 里）。"""
        r = self.result
        for key in ("compounded_oos_return", "degradation", "consistency",
                    "n_folds", "n_skipped", "n_planned_folds", "folds",
                    "skipped", "summary", "elapsed_ms"):
            self.assertIn(key, r, f"缺少顶层字段 {key}")
        # 顶层与 summary 同源（透出不漂移）
        self.assertEqual(
            r["compounded_oos_return"], r["summary"]["compounded_oos_return"]
        )

    def test_fold_record_flat_keys(self) -> None:
        """P0-2 锁：有效折记录带扁平 oos_total_return/oos_sharpe（前端不再回退链）。"""
        folds = self.result["folds"]
        if not folds:
            self.skipTest("合成序列折数为空（区间太短），跳过形状断言")
        for fold in folds:
            for key in ("train_start", "train_end", "test_start", "test_end",
                        "best_params", "is_score", "oos_objective",
                        "oos_degraded", "oos_stats",
                        "oos_total_return", "oos_sharpe"):
                self.assertIn(key, fold, f"折记录缺少字段 {key}")
            # 扁平键与嵌套 stats 同源
            self.assertEqual(
                fold["oos_total_return"],
                (fold["oos_stats"] or {}).get("total_return"),
            )


class AggregateOosEmptyFoldsTest(unittest.TestCase):
    """aggregate_oos 空折口径（Wave 2 挂账修复）：
    无有效折 ≠ 一致性 0%——consistency 必须 None（前端显示「—」），
    复利收益同语义（None，阶段 O review P2-2 统一，防前端误显示 +0.00%）。
    """

    def test_empty_folds_consistency_is_none(self) -> None:
        from app.engine.walkforward import aggregate_oos

        agg = aggregate_oos([], objective="sortino")
        self.assertEqual(agg["n_folds"], 0)
        self.assertIsNone(agg["compounded_oos_return"])
        self.assertIsNone(agg["consistency"])
        self.assertIsNone(agg["degradation"])
        self.assertIsNone(agg["avg_is_objective"])
        self.assertIsNone(agg["avg_oos_objective"])
        self.assertEqual(agg["oos_equity_curve"], [])
        self.assertEqual(agg["param_stability"], {})

    def test_nonempty_folds_consistency_ratio(self) -> None:
        from app.engine.walkforward import aggregate_oos

        recs = [
            {"index": i, "test_end": date(2026, 2, 1), "is_score": 1.0,
             "oos_objective": 1.0, "best_params": {},
             "oos_stats": {"total_return": r}}
            for i, r in enumerate((0.1, -0.05, 0.02))
        ]
        agg = aggregate_oos(recs, objective="sortino")
        self.assertEqual(agg["n_folds"], 3)
        self.assertEqual(agg["consistency"], round(2 / 3, 4))


class OptimizeWorkerPathTest(unittest.TestCase):
    """worker 池派发路径 e2e（阶段 M review 残余风险 2 的处置）：
    _make_run_fn_worker 在 async 入口的 running loop 里被同步循环调用，
    修复前 asyncio.run() 必抛「cannot be called from a running event loop」。
    阈值降到 1 强制走 worker 路径，真 spawn 子进程跑 2 组合。

    环境前提：本用例要求宿主机/CI 的 asyncio selector 唤醒机制正常
    （call_soon_threadsafe 能唤醒裸 await 的 loop）。2026-09-13 实测本仓库
    dev 宿主机（uv python 3.12 / 系统 3.11，Linux 内核环境）存在
    「loop 沉睡不被唤醒」的环境级怪癖（最小复现：手动线程
    call_soon_threadsafe + 裸 await future 永不返回；docker 容器内正常）。
    该环境下本用例自动 skip（worker 池在容器/prod 已端到端验证）。
    """

    def test_worker_path_under_running_loop(self) -> None:
        if not _loop_wakeup_healthy():
            self.skipTest("当前环境 asyncio 唤醒机制异常（已知宿主机怪癖），跳过")
        import app.runner as runner_mod
        from app.api import api_optimize

        old_cache = settings.QUANT_CACHE_DIR
        old_threshold = runner_mod._OPTIMIZE_OFFLOAD_THRESHOLD
        with tempfile.TemporaryDirectory() as tmp:
            _seed_cache(tmp)
            runner_mod._OPTIMIZE_OFFLOAD_THRESHOLD = 1  # 2 组合 > 1 → worker 池
            p1, _p2 = _no_network()
            try:
                # spawn 子进程是独立解释器，不继承父进程对 settings 属性的运行时
                # 篡改——缓存目录必须经环境变量传递（config 从进程环境读，spawn
                # 继承 os.environ）
                with mock.patch.dict("os.environ", {"QUANT_CACHE_DIR": tmp}), \
                     mock.patch.object(settings, "QUANT_CACHE_DIR", tmp), \
                     p1, mock.patch(
                    "app.runner._fetch_names", new=AsyncMock(return_value={})
                ):
                    result = asyncio.run(
                        api_optimize(_optimize_request(), user_id=_UID)
                    )
            finally:
                runner_mod._OPTIMIZE_OFFLOAD_THRESHOLD = old_threshold
            settings.QUANT_CACHE_DIR = old_cache

        self.assertEqual(result["execution"], "worker")
        self.assertEqual(result["n_completed"], 2)
        self.assertEqual(result["n_errors"], 0)
        self.assertIsNotNone(result["best_params"])


def _loop_wakeup_healthy() -> bool:
    """探测当前环境 asyncio selector 是否会被 call_soon_threadsafe 正常唤醒。

    注意探测本身不能用裸 await 轮询（坏环境里探测协程的 sleep 轮询虽能醒，
    但 wait_for/shield 计时器走的是同一套 selector，同样叫不醒）——改为
    独立线程跑一个隔离的 asyncio.run，其内只做一次裸 await future（坏环境
    永不返回），主线程 join 超时兜底判负。
    """
    import threading
    import time as _time

    holder: dict[str, bool] = {}

    def _probe() -> None:
        async def _inner() -> bool:
            loop = asyncio.get_running_loop()
            future = loop.create_future()

            def _t() -> None:
                _time.sleep(0.2)
                loop.call_soon_threadsafe(future.set_result, True)

            threading.Thread(target=_t, daemon=True).start()
            # 裸 await：坏环境里这次 await 永不返回（selector 不唤醒）
            await future
            return True

        try:
            holder["ok"] = asyncio.run(asyncio.wait_for(_inner(), timeout=2.0))
        except Exception:
            holder["ok"] = False

    th = threading.Thread(target=_probe, daemon=True)
    th.start()
    th.join(timeout=5.0)
    return holder.get("ok", False)


if __name__ == "__main__":
    unittest.main()
