"""复权因子缓存新鲜度机制回归测试（P1：qfq 锚定最新交易日，旧缓存除权后失真）。

覆盖点：
- factors.is_stale 三分支：缓存文件不存在 / meta 缺失或损坏（旧缓存兼容，
  视为 stale 触发一次重拉）/ meta 新鲜（fetched_at 在 1 天内）不 stale、
  meta 过期（fetched_at 超过 1 天）stale。
- factors.fetch 写缓存时同步写 meta sidecar（fetched_at = 当日、max_date 正确）。
- api._warm_factor_cache：stale 标的进入补拉列表并调用 factors.fetch；
  新鲜标的不触发 fetch；fetch 抛错时优雅降级不抛出。
"""
from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

try:
    from app.config import settings
    from app.data import factors
    from app.api import _warm_factor_cache

    _DEPS_OK = True
except ImportError as e:  # 宿主机缺依赖（polars/fastapi 等）时整组跳过，不假装通过
    _DEPS_OK = False
    _IMPORT_ERROR = e


def _write_factor_cache(cache_dir: str, symbol: str) -> Path:
    """直接落一个最小因子缓存 parquet（绕过 fetch，隔离被测面）。"""
    import polars as pl

    path = Path(cache_dir) / "factors" / f"symbol={symbol}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(
        {"date": [date(2026, 1, 5), date(2026, 1, 6)], "ex_factor": [0.9, 1.0]}
    ).write_parquet(path)
    return path


def _write_meta(cache_dir: str, symbol: str, fetched_at: date) -> None:
    meta = {
        "symbol": symbol,
        "fetched_at": fetched_at.isoformat(),
        "max_date": "2026-01-06",
        "rows": 2,
    }
    path = Path(cache_dir) / "factors" / f"symbol={symbol}.meta.json"
    path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")


@unittest.skipUnless(_DEPS_OK, f"缺运行依赖（如 polars），在 devcontainer/容器内跑：{_IMPORT_ERROR if not _DEPS_OK else ''}")
class IsStaleTest(unittest.TestCase):
    """is_stale 判定：不存在 / meta 缺失（旧缓存）/ meta 损坏 / 过期 / 新鲜。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._old_cache = settings.QUANT_CACHE_DIR
        settings.QUANT_CACHE_DIR = self._tmp.name

    def tearDown(self) -> None:
        settings.QUANT_CACHE_DIR = self._old_cache
        self._tmp.cleanup()

    def test_missing_cache_file_is_stale(self) -> None:
        self.assertTrue(factors.is_stale("600519.SH"))

    def test_missing_meta_is_stale(self) -> None:
        """旧缓存兼容：只有 parquet 没有 meta → 视为 stale，触发一次重拉。"""
        _write_factor_cache(self._tmp.name, "600519.SH")
        self.assertTrue(factors.is_stale("600519.SH"))

    def test_corrupt_meta_is_stale(self) -> None:
        _write_factor_cache(self._tmp.name, "600519.SH")
        meta = Path(self._tmp.name) / "factors" / "symbol=600519.SH.meta.json"
        meta.write_text("{不是合法 json", encoding="utf-8")
        self.assertTrue(factors.is_stale("600519.SH"))

    def test_fresh_meta_is_not_stale(self) -> None:
        _write_factor_cache(self._tmp.name, "600519.SH")
        _write_meta(self._tmp.name, "600519.SH", date.today())
        self.assertFalse(factors.is_stale("600519.SH"))

    def test_expired_meta_is_stale(self) -> None:
        _write_factor_cache(self._tmp.name, "600519.SH")
        _write_meta(self._tmp.name, "600519.SH", date.today() - timedelta(days=2))
        self.assertTrue(factors.is_stale("600519.SH"))

    def test_boundary_age_respects_max_age_days(self) -> None:
        """恰好 max_age_days 天不算过期，多一天才算（边界含当天拉取的缓存）。"""
        _write_factor_cache(self._tmp.name, "600519.SH")
        _write_meta(self._tmp.name, "600519.SH", date.today() - timedelta(days=1))
        self.assertFalse(factors.is_stale("600519.SH"))
        self.assertTrue(factors.is_stale("600519.SH", max_age_days=0))


@unittest.skipUnless(_DEPS_OK, f"缺运行依赖（如 polars），在 devcontainer/容器内跑：{_IMPORT_ERROR if not _DEPS_OK else ''}")
class FetchWritesMetaTest(unittest.TestCase):
    """fetch 落盘时同步写 meta sidecar，此后 is_stale 判新鲜。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._old_cache = settings.QUANT_CACHE_DIR
        settings.QUANT_CACHE_DIR = self._tmp.name

    def tearDown(self) -> None:
        settings.QUANT_CACHE_DIR = self._old_cache
        self._tmp.cleanup()

    def test_fetch_writes_meta_sidecar(self) -> None:
        rows = [
            {"symbol": "600519.SH", "date": "2026-01-05", "qfq": 0.9},
            {"symbol": "600519.SH", "date": "2026-01-06", "qfq": 1.0},
        ]
        with mock.patch.object(
            factors.client, "fetch_factors", new=mock.AsyncMock(return_value=rows)
        ):
            got = asyncio.run(factors.fetch(["600519.SH"]))
        self.assertIn("600519.SH", got)

        meta_path = Path(self._tmp.name) / "factors" / "symbol=600519.SH.meta.json"
        self.assertTrue(meta_path.exists())
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        self.assertEqual(meta["fetched_at"], date.today().isoformat())
        self.assertEqual(meta["max_date"], "2026-01-06")
        self.assertEqual(meta["rows"], 2)
        # 写完 meta 后缓存视为新鲜，不再触发重拉
        self.assertFalse(factors.is_stale("600519.SH"))


@unittest.skipUnless(_DEPS_OK, f"缺运行依赖（如 polars），在 devcontainer/容器内跑：{_IMPORT_ERROR if not _DEPS_OK else ''}")
class WarmFactorCacheTest(unittest.TestCase):
    """_warm_factor_cache：stale 标的进补拉列表，新鲜标的跳过；失败优雅降级。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._old_cache = settings.QUANT_CACHE_DIR
        settings.QUANT_CACHE_DIR = self._tmp.name

    def tearDown(self) -> None:
        settings.QUANT_CACHE_DIR = self._old_cache
        self._tmp.cleanup()

    def _warm(self, symbols: list[str]) -> None:
        asyncio.run(_warm_factor_cache(symbols))

    def test_stale_symbol_triggers_fetch(self) -> None:
        """meta 过期的标的会出现在 factors.fetch 的补拉列表里。"""
        _write_factor_cache(self._tmp.name, "600519.SH")
        _write_meta(self._tmp.name, "600519.SH", date.today() - timedelta(days=3))
        with mock.patch.object(
            factors, "fetch", new=mock.AsyncMock(return_value={})
        ) as fetch_mock:
            self._warm(["600519.SH"])
        fetch_mock.assert_awaited_once_with(["600519.SH"])

    def test_missing_meta_triggers_fetch(self) -> None:
        """旧缓存（无 meta）触发一次重拉。"""
        _write_factor_cache(self._tmp.name, "000001.SZ")
        with mock.patch.object(
            factors, "fetch", new=mock.AsyncMock(return_value={})
        ) as fetch_mock:
            self._warm(["000001.SZ"])
        fetch_mock.assert_awaited_once_with(["000001.SZ"])

    def test_fresh_symbol_skips_fetch(self) -> None:
        """meta 新鲜的标的不进补拉列表；全部新鲜时完全不调 fetch。"""
        _write_factor_cache(self._tmp.name, "600519.SH")
        _write_meta(self._tmp.name, "600519.SH", date.today())
        with mock.patch.object(
            factors, "fetch", new=mock.AsyncMock(return_value={})
        ) as fetch_mock:
            self._warm(["600519.SH"])
        fetch_mock.assert_not_called()

    def test_mixed_staleness_fetches_only_stale(self) -> None:
        """混合场景：只有 stale 的标的进 fetch 参数。"""
        _write_factor_cache(self._tmp.name, "600519.SH")
        _write_meta(self._tmp.name, "600519.SH", date.today())
        _write_factor_cache(self._tmp.name, "000001.SZ")
        _write_meta(self._tmp.name, "000001.SZ", date.today() - timedelta(days=5))
        with mock.patch.object(
            factors, "fetch", new=mock.AsyncMock(return_value={})
        ) as fetch_mock:
            self._warm(["600519.SH", "000001.SZ"])
        fetch_mock.assert_awaited_once_with(["000001.SZ"])

    def test_fetch_failure_degrades_gracefully(self) -> None:
        """补拉失败只记日志不抛错（缺因子标的按无复权降级口径不变）。"""
        with mock.patch.object(
            factors, "fetch", new=mock.AsyncMock(side_effect=RuntimeError("回源失败"))
        ):
            self._warm(["600519.SH"])  # 不抛即通过


if __name__ == "__main__":
    unittest.main()
