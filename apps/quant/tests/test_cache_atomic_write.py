"""缺陷 1 修复验收：Parquet 缓存写原子性（tmp + os.replace）。

覆盖三处落盘入口：
- data/store.py save（日K 缓存）
- data/client_minute.py save_minute（分钟K 按年缓存）
- data/factors.py fetch 落盘 parquet + _write_meta（因子缓存与 meta sidecar）

验收点：
- 写入经同目录 {name}.tmp.{pid} 中转，os.replace 原子替换；
- 替换发生前读到的是完整旧文件（POSIX rename 原子语义）；
- 写失败不留 tmp 残文件。

缺依赖（polars）时整体 skip（与仓库存量测试的 skipUnless 风格一致，
本机环境无 polars，devcontainer 内全量跑）。
"""
from __future__ import annotations

import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

try:
    import polars as pl

    _HAS_DEPS = True
except ModuleNotFoundError:  # 本机无 polars：skip，不阻塞宿主环境跑其他测试
    pl = None
    _HAS_DEPS = False

_DAILY_SCHEMA = (
    {
        "symbol": pl.String,
        "date": pl.Date,
        "open": pl.Float64,
        "high": pl.Float64,
        "low": pl.Float64,
        "close": pl.Float64,
        "volume": pl.Int64,
        "amount": pl.Float64,
    }
    if _HAS_DEPS
    else {}
)

_MINUTE_SCHEMA = (
    {
        "symbol": pl.String,
        "datetime": pl.Datetime,
        "open": pl.Float64,
        "high": pl.Float64,
        "low": pl.Float64,
        "close": pl.Float64,
        "volume": pl.Float64,
        "amount": pl.Float64,
        "source": pl.String,
    }
    if _HAS_DEPS
    else {}
)


def _spy_replace(bucket: list[str], read_dst: list[bytes] | None = None):
    """包装 os.replace：记录 tmp 源路径；可选在替换瞬间读目标文件字节。

    read_dst 非空时收集 replace 前的目标文件内容——原子写语义下，
    那一刻读到的只能是完整旧文件（或文件不存在）。
    """
    real_replace = os.replace

    def spy(src, dst):
        bucket.append(str(src))
        if read_dst is not None:
            read_dst.append(Path(dst).read_bytes())
        return real_replace(src, dst)

    return spy


class _CacheDirCase(unittest.TestCase):
    """公共脚手架：临时 QUANT_CACHE_DIR。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        from app.config import settings

        patcher = mock.patch.object(settings, "QUANT_CACHE_DIR", self._tmp.name)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _assert_no_tmp_left(self) -> None:
        self.assertEqual(list(Path(self._tmp.name).rglob("*.tmp.*")), [])


@unittest.skipUnless(_HAS_DEPS, "缺 polars（devcontainer 内跑）")
class StoreAtomicWriteTest(_CacheDirCase):
    """data/store.save 的原子写。"""

    def _df(self, close: float) -> "pl.DataFrame":
        return pl.DataFrame(
            {
                "symbol": ["AAPL"],
                "date": [date(2026, 1, 5)],
                "open": [close],
                "high": [close],
                "low": [close],
                "close": [close],
                "volume": [1],
                "amount": [close],
            }
        ).cast(_DAILY_SCHEMA)

    def test_save_uses_tmp_then_replace(self) -> None:
        from app.data import store

        store.save("AAPL", self._df(10.0))  # 先铺一份旧缓存
        target = store._file_of("AAPL")
        before = target.read_bytes()

        seen_tmp: list[str] = []
        read_at_replace: list[bytes] = []
        with mock.patch(
            "app.data.store.os.replace",
            side_effect=_spy_replace(seen_tmp, read_at_replace),
        ):
            store.save("AAPL", self._df(20.0))

        self.assertEqual(len(seen_tmp), 1)
        self.assertIn(f"{target.name}.tmp.", seen_tmp[0])  # 经 tmp 中转
        self.assertEqual(read_at_replace, [before])  # 替换前旧文件完整可读
        self.assertEqual(store.load("AAPL")["close"][0], 20.0)  # 新内容生效
        self._assert_no_tmp_left()

    def test_save_failure_leaves_no_tmp(self) -> None:
        from app.data import store

        store.save("AAPL", self._df(10.0))
        target = store._file_of("AAPL")
        before = target.read_bytes()

        with mock.patch.object(
            pl.DataFrame, "write_parquet", side_effect=OSError("disk full")
        ):
            with self.assertRaises(OSError):
                store.save("AAPL", self._df(20.0))

        self.assertEqual(target.read_bytes(), before)  # 旧文件原样
        self._assert_no_tmp_left()


@unittest.skipUnless(_HAS_DEPS, "缺 polars（devcontainer 内跑）")
class MinuteAtomicWriteTest(_CacheDirCase):
    """data/client_minute.save_minute 的原子写。"""

    def _df(self) -> "pl.DataFrame":
        import datetime as dt

        return pl.DataFrame(
            {
                "symbol": ["600519.SH"],
                "datetime": [dt.datetime(2026, 1, 5, 9, 31)],
                "open": [10.0],
                "high": [10.0],
                "low": [10.0],
                "close": [10.0],
                "volume": [1.0],
                "amount": [10.0],
                "source": ["test"],
            }
        ).cast(_MINUTE_SCHEMA)

    def test_save_minute_atomic(self) -> None:
        from app.data import client_minute

        client_minute.save_minute("600519.SH", 2026, self._df())
        target = client_minute._file_of("600519.SH", 2026)

        seen_tmp: list[str] = []
        with mock.patch(
            "app.data.client_minute.os.replace",
            side_effect=_spy_replace(seen_tmp),
        ):
            client_minute.save_minute("600519.SH", 2026, self._df())

        self.assertEqual(len(seen_tmp), 1)
        self.assertIn(f"{target.name}.tmp.", seen_tmp[0])
        self._assert_no_tmp_left()

    def test_save_minute_failure_leaves_no_tmp(self) -> None:
        from app.data import client_minute

        with mock.patch.object(
            pl.DataFrame, "write_parquet", side_effect=OSError("disk full")
        ):
            with self.assertRaises(OSError):
                client_minute.save_minute("600519.SH", 2026, self._df())

        self.assertFalse(client_minute._file_of("600519.SH", 2026).exists())
        self._assert_no_tmp_left()


@unittest.skipUnless(_HAS_DEPS, "缺 polars（devcontainer 内跑）")
class FactorsAtomicWriteTest(_CacheDirCase):
    """data/factors 的 parquet 落盘与 _write_meta 原子写。"""

    def _factor_df(self) -> "pl.DataFrame":
        return pl.DataFrame(
            {"date": [date(2026, 1, 5)], "ex_factor": [1.0]}
        ).cast({"date": pl.Date, "ex_factor": pl.Float64})

    def test_write_meta_atomic(self) -> None:
        from app.data import factors

        seen_tmp: list[str] = []
        with mock.patch(
            "app.data.factors.os.replace", side_effect=_spy_replace(seen_tmp)
        ):
            factors._write_meta("600519.SH", self._factor_df())

        meta_path = factors._meta_of("600519.SH")
        self.assertEqual(len(seen_tmp), 1)
        self.assertIn(f"{meta_path.name}.tmp.", seen_tmp[0])
        self.assertTrue(meta_path.exists())
        self._assert_no_tmp_left()

    def test_write_meta_failure_leaves_no_tmp(self) -> None:
        from app.data import factors

        # write_text 抛错：meta 写失败只记日志（既有降级语义），且不留 tmp 残文件
        with mock.patch.object(
            Path, "write_text", side_effect=OSError("disk full")
        ):
            factors._write_meta("600519.SH", self._factor_df())  # 不抛错

        self.assertFalse(factors._meta_of("600519.SH").exists())
        self._assert_no_tmp_left()

    def test_fetch_persists_atomically(self) -> None:
        """fetch 落盘 parquet + meta 都走 tmp + replace（mock data-api 响应）。"""
        import asyncio

        from app.data import factors

        rows = [
            {"symbol": "600519.SH", "date": "2026-01-05", "qfq": 1.0},
            {"symbol": "600519.SH", "date": "2026-01-06", "qfq": 0.9},
        ]
        seen_tmp: list[str] = []
        with mock.patch(
            "app.data.client.fetch_factors", new=mock.AsyncMock(return_value=rows)
        ):
            with mock.patch(
                "app.data.factors.os.replace", side_effect=_spy_replace(seen_tmp)
            ):
                result = asyncio.run(factors.fetch(["600519.SH"]))

        self.assertIn("600519.SH", result)
        parquet_path = factors._file_of("600519.SH")
        meta_path = factors._meta_of("600519.SH")
        # parquet + meta 两次原子替换，都经 tmp 中转
        self.assertEqual(len(seen_tmp), 2)
        self.assertTrue(any(f"{parquet_path.name}.tmp." in s for s in seen_tmp))
        self.assertTrue(any(f"{meta_path.name}.tmp." in s for s in seen_tmp))
        self._assert_no_tmp_left()


if __name__ == "__main__":
    unittest.main()
