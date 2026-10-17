"""矩阵内存优化（方向 A float32 降内存 / 方向 B 主进程只预拉）测试。

覆盖：
1. build 默认产出 float32 字段矩阵（环境变量 QUANT_MATRIX_DTYPE=float64 可回退）。
2. 同一份数据 float32 矩阵内存恰为 float64 的一半。
3. prefetch_async 只补拉落盘返回覆盖率摘要（不物化矩阵）；补拉失败降级不抛错。
4. build_async 兼容包装：prefetch + build 一步到位（旧调用方语义不变）。
"""
from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from datetime import date, timedelta
from unittest import mock

import numpy as np
import polars as pl

from app.config import settings
from app.data import store
from app.matrix import build, build_async, prefetch_async

SYM_A = "AAA"
SYM_B = "BBB"
_D0 = date(2026, 1, 5)


def _frame(symbol: str, d0: date, closes: list[float]) -> pl.DataFrame:
    """合成单标的日K 帧（与 test_matrix_prefetch 同风格，OHLC 平值）。"""
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
        self._tmp = tempfile.TemporaryDirectory()
        self._old = settings.QUANT_CACHE_DIR
        settings.QUANT_CACHE_DIR = self._tmp.name
        # dtype 环境变量逐用例隔离（默认 float32 路径不能受外部环境影响）
        self._old_dtype_env = os.environ.pop("QUANT_MATRIX_DTYPE", None)

    def tearDown(self) -> None:
        settings.QUANT_CACHE_DIR = self._old
        if self._old_dtype_env is not None:
            os.environ["QUANT_MATRIX_DTYPE"] = self._old_dtype_env
        else:
            os.environ.pop("QUANT_MATRIX_DTYPE", None)
        self._tmp.cleanup()


class TestMatrixDtype(_CacheDirCase):
    """方向 A：矩阵字段默认 float32，内存减半，float64 可回退。"""

    def test_build_defaults_to_float32(self) -> None:
        store.save(SYM_A, _frame(SYM_A, _D0, [10.0, 11.0, 12.0]))
        m = build([SYM_A], _D0, _D0 + timedelta(days=2))
        for f in ("open", "high", "low", "close", "volume", "amount"):
            self.assertEqual(getattr(m, f).dtype, np.float32, f)

    def test_build_float64_fallback_via_env(self) -> None:
        os.environ["QUANT_MATRIX_DTYPE"] = "float64"
        store.save(SYM_A, _frame(SYM_A, _D0, [10.0, 11.0, 12.0]))
        m = build([SYM_A], _D0, _D0 + timedelta(days=2))
        self.assertEqual(m.close.dtype, np.float64)

    def test_build_explicit_dtype_overrides_env(self) -> None:
        os.environ["QUANT_MATRIX_DTYPE"] = "float64"
        store.save(SYM_A, _frame(SYM_A, _D0, [10.0, 11.0, 12.0]))
        m = build([SYM_A], _D0, _D0 + timedelta(days=2), dtype=np.float32)
        self.assertEqual(m.close.dtype, np.float32)

    def test_float32_memory_is_half_of_float64(self) -> None:
        """内存对比断言：同一批 symbol，float32 矩阵字段总字节数恰为 float64 的一半。"""
        closes = [10.0 + i for i in range(60)]
        for sym in (SYM_A, SYM_B):
            store.save(sym, _frame(sym, _D0, closes))
        end = _D0 + timedelta(days=59)

        def _total_nbytes(m) -> int:
            return sum(
                getattr(m, f).nbytes
                for f in ("open", "high", "low", "close", "volume", "amount")
            )

        m32 = build([SYM_A, SYM_B], _D0, end, dtype=np.float32)
        m64 = build([SYM_A, SYM_B], _D0, end, dtype=np.float64)
        self.assertEqual(m32.shape, m64.shape)
        self.assertEqual(_total_nbytes(m32) * 2, _total_nbytes(m64))

    def test_float32_values_no_observable_deviation(self) -> None:
        """float32 降级不引入可观测数值偏差（价格量级相对误差 ~1e-7）。"""
        closes = [1234.56, 1235.78, 0.01, 9999.99]
        store.save(SYM_A, _frame(SYM_A, _D0, closes))
        m32 = build([SYM_A], _D0, _D0 + timedelta(days=3), dtype=np.float32)
        m64 = build([SYM_A], _D0, _D0 + timedelta(days=3), dtype=np.float64)
        np.testing.assert_allclose(
            m32.close, m64.close.astype(np.float32), rtol=1e-6, atol=0
        )
        np.testing.assert_allclose(
            m32.close.astype(np.float64), m64.close, rtol=1e-6, atol=0
        )


class TestPrefetchAsync(_CacheDirCase):
    """方向 B：prefetch_async 只补拉落盘返回覆盖率摘要，不物化矩阵。"""

    def test_prefetch_full_cache_hit(self) -> None:
        store.save(SYM_A, _frame(SYM_A, _D0, [10.0, 11.0]))
        end = _D0 + timedelta(days=1)
        with mock.patch("app.data.client.fetch_bars") as fb:
            summary = asyncio.run(prefetch_async([SYM_A], _D0, end))
        fb.assert_not_called()
        self.assertEqual(summary["coverage"], 1.0)
        self.assertEqual(summary["covered"], 1)
        self.assertEqual(summary["total"], 1)

    def test_prefetch_fills_missing_and_reports_coverage(self) -> None:
        store.save(SYM_A, _frame(SYM_A, _D0, [10.0, 11.0]))
        end = _D0 + timedelta(days=1)
        with mock.patch(
            "app.data.client.fetch_bars",
            new=mock.AsyncMock(return_value=_bars(SYM_B, _D0, [20.0, 21.0])),
        ):
            summary = asyncio.run(prefetch_async([SYM_A, SYM_B], _D0, end))
        self.assertEqual(summary["coverage"], 1.0)
        self.assertEqual(summary["missing"], 1)
        # 补拉已落盘：同步 build 直读缓存可见 BBB 数据
        m = build([SYM_A, SYM_B], _D0, end)
        j = m.symbols.index(SYM_B)
        self.assertAlmostEqual(float(m.close[0, j]), 20.0, places=5)

    def test_prefetch_fetch_failure_degrades(self) -> None:
        """补拉整体失败：不抛错，覆盖率按未覆盖计（0）。"""
        with mock.patch(
            "app.data.client.fetch_bars",
            new=mock.AsyncMock(side_effect=RuntimeError("数据源故障")),
        ):
            summary = asyncio.run(prefetch_async([SYM_A], _D0, _D0 + timedelta(days=1)))
        self.assertEqual(summary["coverage"], 0.0)
        self.assertEqual(summary["covered"], 0)
        self.assertEqual(summary["missing"], 1)

    def test_prefetch_partial_fetch_reports_partial_coverage(self) -> None:
        """部分标的补拉无数据：覆盖率按实计（1/2）。"""
        store.save(SYM_A, _frame(SYM_A, _D0, [10.0, 11.0]))
        end = _D0 + timedelta(days=1)
        with mock.patch(
            "app.data.client.fetch_bars", new=mock.AsyncMock(return_value=[])
        ):
            summary = asyncio.run(prefetch_async([SYM_A, SYM_B], _D0, end))
        self.assertEqual(summary["coverage"], 0.5)
        self.assertEqual(summary["covered"], 1)

    def test_prefetch_empty_symbols(self) -> None:
        summary = asyncio.run(prefetch_async([], _D0, _D0))
        self.assertEqual(summary["total"], 0)
        self.assertEqual(summary["coverage"], 0.0)


class TestBuildAsyncCompat(_CacheDirCase):
    """build_async 兼容包装：prefetch + build 一步到位（旧调用方语义不变）。"""

    def test_build_async_returns_matrix_with_prefetched_data(self) -> None:
        end = _D0 + timedelta(days=1)
        with mock.patch(
            "app.data.client.fetch_bars",
            new=mock.AsyncMock(return_value=_bars(SYM_A, _D0, [10.0, 11.0])),
        ):
            m = asyncio.run(build_async([SYM_A], _D0, end))
        self.assertEqual(m.symbols, [SYM_A])
        j = m.symbols.index(SYM_A)
        self.assertAlmostEqual(float(m.close[0, j]), 10.0, places=5)
        # 默认 float32（方向 A 口径贯穿兼容包装）
        self.assertEqual(m.close.dtype, np.float32)


if __name__ == "__main__":
    unittest.main()
