"""回测缓存冷启动修复（matrix.build_async 按需回源补拉）测试。

覆盖场景（对应 prod 事故：容器重建后缓存目录为空，回测全员全 NaN 零成交）：
1. 缓存全命中：不发任何网络请求（client.fetch_bars 未被调用）。
2. 部分标的缺失：只对缺失标的批量补拉、merge 落缓存、矩阵含补拉后数据。
3. 补拉失败降级：fetch_bars 抛错，矩阵仍返回（缺失标的全 NaN），不抛错。
4. 区间部分覆盖：缓存只有中段数据，判定为缺失并补拉首尾缺口。
5. run_backtest_async 端到端：空缓存 + mock fetch_bars → 回测出信号/成交。
6. worker 纪律：同步 run_backtest/build 不做回源（回归保证）。
"""
from __future__ import annotations

import asyncio
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

import polars as pl

from app.config import settings
from app.data import store
from app.matrix import build, build_async

SYM_A = "AAA"
SYM_B = "BBB"
_D0 = date(2026, 1, 5)


def _frame(symbol: str, d0: date, closes: list[float]) -> pl.DataFrame:
    """合成单标的日K 帧（连续自然日，OHLC 平值便于断言）。"""
    n = len(closes)
    dates = [d0 + timedelta(days=i) for i in range(n)]
    return pl.DataFrame({
        "symbol": [symbol] * n,
        "date": dates,
        "open": closes,
        "high": closes,
        "low": closes,
        "close": closes,
        "volume": [1_000_000] * n,
        "amount": [c * 1e6 for c in closes],
    })


def _bars(symbol: str, d0: date, closes: list[float]) -> list[dict]:
    """合成 /api/bars 响应行（fetch_bars 的 mock 返回）。"""
    return [
        {"symbol": symbol, "date": (d0 + timedelta(days=i)).isoformat(),
         "open": c, "high": c, "low": c, "close": c,
         "volume": 1_000_000, "amount": c * 1e6}
        for i, c in enumerate(closes)
    ]


class _CacheDirCase(unittest.TestCase):
    """每个用例独立临时缓存目录（settings.QUANT_CACHE_DIR 换绑后还原）。"""

    def setUp(self) -> None:
        self._old_cache = settings.QUANT_CACHE_DIR
        self._tmp = tempfile.TemporaryDirectory()
        settings.QUANT_CACHE_DIR = self._tmp.name

    def tearDown(self) -> None:
        settings.QUANT_CACHE_DIR = self._old_cache
        self._tmp.cleanup()


class BuildAsyncTest(_CacheDirCase):
    def test_all_cached_no_network(self) -> None:
        """缓存全命中：fetch_bars 不应被调用。"""
        start, end = _D0, _D0 + timedelta(days=9)
        store.save(SYM_A, _frame(SYM_A, start, [10.0] * 10))
        with mock.patch(
            "app.data.client.fetch_bars", new=mock.AsyncMock()
        ) as m_fetch:
            matrix = asyncio.run(build_async([SYM_A], start, end))
        m_fetch.assert_not_called()
        self.assertEqual(matrix.symbols, [SYM_A])
        self.assertEqual(len(matrix.dates), 10)

    def test_partial_missing_prefetch_only_missing(self) -> None:
        """SYM_A 已缓存、SYM_B 全缺：只对 SYM_B 补拉，落缓存且矩阵有数据。"""
        start, end = _D0, _D0 + timedelta(days=4)
        store.save(SYM_A, _frame(SYM_A, start, [10.0] * 5))
        fake = mock.AsyncMock(return_value=_bars(SYM_B, start, [20.0] * 5))
        with mock.patch("app.data.client.fetch_bars", new=fake):
            matrix = asyncio.run(build_async([SYM_A, SYM_B], start, end))
        # 只对缺失标的批量补拉一次
        fake.assert_awaited_once()
        args = fake.await_args
        self.assertEqual(args.args[0], [SYM_B])
        self.assertEqual((args.args[1], args.args[2]), (start, end))
        # 补拉结果已落缓存（再读 store 能读到）
        self.assertEqual(store.load(SYM_B).height, 5)
        # 矩阵含补拉后数据：SYM_B 列无 NaN
        j = matrix.symbols.index(SYM_B)
        self.assertFalse(any(v != v for v in matrix.close[:, j]))
        self.assertEqual(matrix.close[0, j], 20.0)

    def test_fetch_failure_degrades_to_nan(self) -> None:
        """补拉抛错：矩阵照常返回，缺失标的全 NaN，不抛错。"""
        start, end = _D0, _D0 + timedelta(days=4)
        store.save(SYM_A, _frame(SYM_A, start, [10.0] * 5))
        fake = mock.AsyncMock(side_effect=RuntimeError("data-api 不可达"))
        with mock.patch("app.data.client.fetch_bars", new=fake):
            matrix = asyncio.run(build_async([SYM_A, SYM_B], start, end))
        j_b = matrix.symbols.index(SYM_B)
        self.assertTrue(all(v != v for v in matrix.close[:, j_b]))
        j_a = matrix.symbols.index(SYM_A)
        self.assertEqual(matrix.close[0, j_a], 10.0)

    def test_fetch_returns_nothing_degrades_to_nan(self) -> None:
        """补拉成功但返回空（上游无数据）：缺失标的保留全 NaN，不落缓存。"""
        start, end = _D0, _D0 + timedelta(days=4)
        fake = mock.AsyncMock(return_value=[])
        with mock.patch("app.data.client.fetch_bars", new=fake):
            matrix = asyncio.run(build_async([SYM_B], start, end))
        self.assertEqual(matrix.symbols, [SYM_B])
        self.assertEqual(matrix.shape[0], 0)  # 全 NaN 列：无交易日轴
        self.assertEqual(store.load(SYM_B).height, 0)

    def test_partial_range_coverage_triggers_gap_fetch(self) -> None:
        """缓存只盖住中段（3-5 月），回测区间 1-6 月：判定缺失并补拉首尾缺口。"""
        start, end = date(2026, 1, 1), date(2026, 6, 30)
        mid0, mid1 = date(2026, 3, 1), date(2026, 5, 31)
        store.save(SYM_A, _frame(SYM_A, mid0, [10.0] * ((mid1 - mid0).days + 1)))
        captured: list[tuple] = []

        async def _fake_fetch(symbols, s, e, **_kw):
            captured.append((symbols, s, e))
            return _bars(SYM_A, start, [10.0] * ((end - start).days + 1))

        with mock.patch("app.data.client.fetch_bars", new=_fake_fetch):
            matrix = asyncio.run(build_async([SYM_A], start, end))
        self.assertEqual(len(captured), 1)
        # 补拉请求覆盖整个回测区间（fetch_bars 自带分片分窗）
        self.assertEqual((captured[0][1], captured[0][2]), (start, end))
        # 补拉后缓存首尾日期盖住整个区间
        df = store.load(SYM_A)
        self.assertEqual((df["date"].min(), df["date"].max()), (start, end))
        self.assertGreaterEqual(matrix.shape[0], (end - start).days)

    def test_sync_build_no_prefetch(self) -> None:
        """回归保证：同步 build() 只读缓存，绝不触发回源（worker 纪律）。"""
        start, end = _D0, _D0 + timedelta(days=4)
        with mock.patch(
            "app.data.client.fetch_bars", new=mock.AsyncMock()
        ) as m_fetch:
            matrix = build([SYM_B], start, end)
        m_fetch.assert_not_called()
        self.assertEqual(matrix.symbols, [SYM_B])


class RunBacktestAsyncPrefetchTest(_CacheDirCase):
    """端到端：空缓存 + mock fetch_bars → run_backtest_async 出信号/成交。"""

    # 与 test_result_wiring 同款合成序列：平盘 → 反弹出金叉 → 回落出死叉，保证有成交
    _N = 45
    _CLOSES = (
        [10.0] * 20
        + [10.3, 10.6, 10.9, 11.2, 11.5]
        + [11.3, 11.0, 10.7]
        + [10.6] * 17
    )

    def _registry(self):
        from app.strategy import StrategyRegistry
        from app.strategy import loader as strategy_loader

        return StrategyRegistry(
            {"builtin": Path(strategy_loader.__file__).parent / "builtin"}
        )

    def test_cold_cache_backtest_produces_trades(self) -> None:
        from app.runner import run_backtest_async

        start = _D0
        end = _D0 + timedelta(days=self._N - 1)
        fake = mock.AsyncMock(
            return_value=_bars(SYM_A, start, list(self._CLOSES))
        )
        # benchmark/names 也走网络，一并 mock 掉（本用例只验证日K 回源链路）
        with (
            mock.patch("app.data.client.fetch_bars", new=fake),
            mock.patch("app.runner._fetch_benchmark", new=mock.AsyncMock(return_value=None)),
            mock.patch("app.runner._fetch_names", new=mock.AsyncMock(return_value={})),
        ):
            out = asyncio.run(
                run_backtest_async(
                    [SYM_A], "ma_golden_cross", start, end,
                    params={"require_above_ma60": False, "vol_ratio_min": 0.0},
                    registry=self._registry(),
                )
            )
        fake.assert_awaited_once()
        # 补拉已落缓存（worker/后续同步调用直接读缓存即可）
        self.assertEqual(store.load(SYM_A).height, self._N)
        # 冷缓存经回源补拉后回测出信号与成交（修复前的 prod 事故为 0 笔）
        self.assertGreater(out["selection_stats"]["signals_entry"], 0)
        self.assertGreater(out["stats"]["trades"], 0)

    def test_cold_cache_backtest_fetch_failure_empty(self) -> None:
        """边界：fetch_bars 失败时 run_backtest_async 仍返回全零骨架（不抛错）。"""
        from app.runner import run_backtest_async

        start = _D0
        end = _D0 + timedelta(days=self._N - 1)
        with (
            mock.patch(
                "app.data.client.fetch_bars",
                new=mock.AsyncMock(side_effect=RuntimeError("断网")),
            ),
            mock.patch("app.runner._fetch_benchmark", new=mock.AsyncMock(return_value=None)),
            mock.patch("app.runner._fetch_names", new=mock.AsyncMock(return_value={})),
        ):
            out = asyncio.run(
                run_backtest_async(
                    [SYM_A], "ma_golden_cross", start, end, registry=self._registry()
                )
            )
        self.assertEqual(out["stats"]["trades"], 0)
        self.assertEqual(out["equity_curve"], [])


if __name__ == "__main__":
    unittest.main()
