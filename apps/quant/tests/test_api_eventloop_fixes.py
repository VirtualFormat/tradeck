"""API 层遗留缺陷修复测试（screen 线程化 / optimize 线程化 / 预拉覆盖率前置 503）。

与 test_optimize_api 同款风格：直接调用端点协程函数 + mock 屏蔽网络与重计算，
不起 TestClient（本仓库 starlette 版本的 TestClient 存在挂起问题）。

缺陷 1：api_screen 的同步 screen() 必须经 asyncio.to_thread 甩线程池，
        全市场重计算不再阻塞事件循环。
缺陷 2：_run_optimize_route 的 runner_fn 调用必须经 asyncio.to_thread 甩线程池，
        进程内串行路径（小网格 × 全市场）不再卡死事件循环。
缺陷 3：api_backtest / api_backtest_run 登记/执行前检查矩阵覆盖率，
        数据源大面积失败（覆盖率 < 50%）直接 503，不登记任务不让 worker 白跑。

宿主机缺 polars/numpy 时显式跳过（CI/容器内依赖齐全则全量跑）。
"""
from __future__ import annotations

import asyncio
import tempfile
import unittest
from datetime import date, timedelta
from unittest import mock
from unittest.mock import AsyncMock

try:
    import numpy as np
    import polars as pl

    from app.config import settings
    from app.data import store

    _DEPS_OK = True
except ImportError:  # 宿主机裸环境缺依赖：显式跳过（AST/走查兜底）
    _DEPS_OK = False

_UID = "default"  # 直接调端点函数时显式传 user_id（绕过 FastAPI Depends 默认值）
_SYM = "AAPL"
_D0 = date(2026, 1, 5)
_END = date(2026, 2, 20)
# MarketMatrix 六个字段（与 matrix.market.FIELDS 一致，避免测试 import matrix 模块本体）
_FIELDS = ("open", "high", "low", "close", "volume", "amount")


def _make_matrix(n_symbols: int, n_data: int):
    """构造合成 MarketMatrix：前 n_data 列有数据，其余全 NaN。"""
    from app.matrix.market import MarketMatrix

    close = np.full((1, n_symbols), np.nan)
    close[:, :n_data] = 10.0
    kwargs = {f: close.copy() for f in _FIELDS}
    return MarketMatrix(
        dates=[_D0], symbols=[f"S{i:03d}" for i in range(n_symbols)], **kwargs,
    )


@unittest.skipUnless(_DEPS_OK, "缺 numpy/polars 依赖，跳过运行时测试")
class ScreenOffloadTest(unittest.TestCase):
    """缺陷 1：screen() 同步调用经 asyncio.to_thread 甩线程池。"""

    def test_screen_runs_via_to_thread(self) -> None:
        from app import api as quant_api

        req = quant_api.ScreenRequest(
            symbols=[_SYM], strategy_id="ma_golden_cross", start=_D0, end=_END,
        )
        with tempfile.TemporaryDirectory() as tmp:
            settings.QUANT_CACHE_DIR = tmp  # build_async 走空缓存纯本地读
            with (
                mock.patch.object(quant_api, "_registry", return_value=mock.Mock()),
                # build_async 会回源补拉（缓存为空），mock 掉避免网络/慢
                mock.patch(
                    "app.data.client.fetch_bars", new=AsyncMock(return_value=[]),
                ),
                # api.py 里是 from app.screener import screen（本地引用），
                # patch 目标必须是 app.api.screen
                mock.patch(
                    "app.api.screen", return_value=mock.Mock(rows=[], total=0),
                ) as screen_mock,
                mock.patch(
                    "app.api.asyncio.to_thread", new=AsyncMock(return_value=None),
                ) as to_thread_mock,
            ):
                # to_thread 被 mock 成 None 后 rows 列表推导会 TypeError，
                # 这里只关心调用链路，吞掉后续异常
                try:
                    asyncio.run(quant_api.api_screen(req, user_id=_UID))
                except (TypeError, AttributeError):
                    pass

        # 链路断言：to_thread 首个位置参数必须指向 screener.screen 本体，
        # 即 screen() 经线程池执行而非直接在事件循环上同步调用
        to_thread_mock.assert_awaited_once()
        self.assertIs(to_thread_mock.await_args.args[0], screen_mock)


@unittest.skipUnless(_DEPS_OK, "缺 numpy/polars 依赖，跳过运行时测试")
class OptimizeOffloadTest(unittest.TestCase):
    """缺陷 2：runner_fn 经 asyncio.to_thread 甩线程池（进程内路径不堵事件循环）。"""

    def _request(self):
        from app.api import OptimizeRequest

        return OptimizeRequest(
            symbols=[_SYM],
            strategy_id="ma_golden_cross",
            start=_D0,
            end=_END,
            param_grid={"vol_ratio_min": [0.0, 1.0]},
            base_params={"require_above_ma60": False},
        )

    def test_runner_fn_runs_via_to_thread(self) -> None:
        from app import api as quant_api

        with tempfile.TemporaryDirectory() as tmp:
            settings.QUANT_CACHE_DIR = tmp
            with (
                mock.patch.object(quant_api, "_warm_factor_cache", new=AsyncMock()),
                # build_async 会回源补拉（缓存为空），mock 掉避免网络/慢
                mock.patch(
                    "app.data.client.fetch_bars", new=AsyncMock(return_value=[]),
                ),
                mock.patch("app.runner._fetch_benchmark", new=AsyncMock(return_value=None)),
                mock.patch("app.runner._fetch_names", new=AsyncMock(return_value={})),
                mock.patch(
                    "app.api._run_optimize_blocking",
                    return_value={"execution": "inprocess"},
                ) as blocking_mock,
                mock.patch(
                    "app.api.asyncio.to_thread",
                    new=AsyncMock(return_value={"execution": "inprocess"}),
                ) as to_thread_mock,
            ):
                out = asyncio.run(
                    quant_api.api_optimize(self._request(), user_id=_UID),
                )

        self.assertEqual(out, {"execution": "inprocess"})
        # 链路断言：to_thread 首个位置参数必须是 _run_optimize_blocking 包装器，
        # 即整个 runner_fn（含进程内串行路径）不再跑在事件循环上
        to_thread_mock.assert_awaited_once()
        self.assertIs(to_thread_mock.await_args.args[0], blocking_mock)

    def test_blocking_wrapper_runs_coroutine(self) -> None:
        """_run_optimize_blocking 本体：线程内 asyncio.run 驱动 runner_fn 协程。"""
        from app.api import _run_optimize_blocking

        async def _fake_runner(*args, **kwargs):
            return {"args": list(args), "kwargs": kwargs}

        out = _run_optimize_blocking(_fake_runner, "a", 1, objective="sharpe")
        self.assertEqual(out, {"args": ["a", 1], "kwargs": {"objective": "sharpe"}})


@unittest.skipUnless(_DEPS_OK, "缺 numpy/polars 依赖，跳过运行时测试")
class MatrixCoverageGateTest(unittest.TestCase):
    """缺陷 3：预拉覆盖率门槛——_matrix_coverage 的判定与 503 前置。"""

    def test_coverage_ratio(self) -> None:
        from app.api import _matrix_coverage

        self.assertAlmostEqual(_matrix_coverage(_make_matrix(10, 6)), 0.6)
        self.assertAlmostEqual(_matrix_coverage(_make_matrix(10, 0)), 0.0)
        self.assertAlmostEqual(_matrix_coverage(_make_matrix(10, 10)), 1.0)

    def test_empty_matrix_zero_coverage(self) -> None:
        from app.api import _matrix_coverage
        from app.matrix.market import MarketMatrix

        empty = MarketMatrix(
            dates=[], symbols=[],
            **{f: np.full((0, 0), np.nan) for f in _FIELDS},
        )
        self.assertEqual(_matrix_coverage(empty), 0.0)

    def test_below_threshold_raises_503(self) -> None:
        from fastapi import HTTPException

        from app.api import _check_matrix_coverage_or_503

        with self.assertRaises(HTTPException) as ctx:
            _check_matrix_coverage_or_503(_make_matrix(10, 3), ["S"] * 10)
        self.assertEqual(ctx.exception.status_code, 503)
        self.assertIn("覆盖率", ctx.exception.detail)

    def test_at_or_above_threshold_passes(self) -> None:
        from app.api import _check_matrix_coverage_or_503

        # 恰好 50%（部分缺失常态：新股/停牌）必须放行，不误伤
        _check_matrix_coverage_or_503(_make_matrix(10, 5), ["S"] * 10)
        _check_matrix_coverage_or_503(_make_matrix(10, 10), ["S"] * 10)


@unittest.skipUnless(_DEPS_OK, "缺 numpy/polars 依赖，跳过运行时测试")
class BacktestCoverageGateRouteTest(unittest.TestCase):
    """缺陷 3 路由层：数据源大面积失败时不登记任务/不调 worker，直接 503。"""

    def _request(self):
        from app.api import BacktestRequest

        return BacktestRequest(
            symbols=[_SYM], strategy_id="ma_golden_cross", start=_D0, end=_END,
        )

    def test_backtest_run_503_when_prefetch_fails(self) -> None:
        """任务化入口：fetch_bars 整体失败 → 全 NaN 矩阵 → 503，注册表无新任务。"""
        from fastapi import HTTPException

        from app import api as quant_api
        from app.tasks import get_registry

        reg = get_registry()
        before = len(reg.list())  # 全局单例，先记基线（其他测试可能留有任务）
        with tempfile.TemporaryDirectory() as tmp:
            settings.QUANT_CACHE_DIR = tmp  # 空缓存：build_async 回源补拉
            with (
                mock.patch.object(
                    quant_api, "_warm_factor_cache", new=AsyncMock(),
                ) as warm_mock,
                mock.patch(
                    "app.api._fetch_benchmark", new=AsyncMock(return_value=None),
                ),
                mock.patch(
                    "app.api._fetch_names", new=AsyncMock(return_value={}),
                ),
                mock.patch(
                    "app.data.client.fetch_bars",
                    new=AsyncMock(side_effect=RuntimeError("数据源整体故障")),
                ),
            ):
                with self.assertRaises(HTTPException) as ctx:
                    asyncio.run(quant_api.api_backtest_run(self._request(), user_id=_UID))

        self.assertEqual(ctx.exception.status_code, 503)
        # 未登记任务：注册表任务数不变
        self.assertEqual(len(reg.list()), before)
        # 503 前置在因子预拉之前：暖因子/分钟K 等重活不白跑
        warm_mock.assert_not_awaited()

    def test_backtest_sync_503_when_prefetch_fails(self) -> None:
        """同步入口：同样 503，且不调 run_backtest_in_worker。"""
        from fastapi import HTTPException

        from app import api as quant_api

        with tempfile.TemporaryDirectory() as tmp:
            settings.QUANT_CACHE_DIR = tmp  # 空缓存：build_async 回源补拉
            with (
                mock.patch.object(quant_api, "_warm_factor_cache", new=AsyncMock()),
                mock.patch(
                    "app.api._fetch_benchmark", new=AsyncMock(return_value=None),
                ),
                mock.patch(
                    "app.api._fetch_names", new=AsyncMock(return_value={}),
                ),
                mock.patch(
                    "app.data.client.fetch_bars",
                    new=AsyncMock(side_effect=RuntimeError("数据源整体故障")),
                ),
                mock.patch("app.api.run_backtest_in_worker", new=AsyncMock()) as worker_mock,
            ):
                with self.assertRaises(HTTPException) as ctx:
                    asyncio.run(quant_api.api_backtest(self._request(), user_id=_UID))

        self.assertEqual(ctx.exception.status_code, 503)
        worker_mock.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
