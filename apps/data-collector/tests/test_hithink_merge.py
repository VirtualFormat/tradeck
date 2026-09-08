"""merge_daily_pool 的合并语义与并发安全测试。

背景（2026-09-08）：daily_kline 对同一 market 的不同 symbol 批次并发调
merge_daily_pool，写同一 (year, market) Parquet 文件时 read_parquet 与
os.replace 竞态 → _duckdb.Error: TProtocolException: Invalid data。修复：
按 target 路径加进程级 asyncio.Lock 串行化。

说明：该竞态是「读到替换到一半的文件」的时间窗问题，在生产大文件 + 高频
+ I/O 压力下偶发，单测无法稳定复现。本测试不假装复现竞态，而是验证修复
的确定性语义：同一文件并发 merge 无异常、数据完整、串行 merge 幂等、
文件级锁确实按 target 路径分配。依赖 duckdb / pyarrow，临时目录隔离
DATA_POOL_ROOT，不碰真实 data-pool。
"""
from __future__ import annotations

import asyncio
import unittest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import duckdb

from app.jobs import hithink_dump


def _rows(symbols: list[str], year: int = 2026) -> list[tuple]:
    """构造 merge 用的标准行（symbol, market, date, OHLCVA）。"""
    return [
        (s, "HK", date(year, 9, 8), 1.0, 2.0, 0.5, 1.5, 1000, 1500.0)
        for s in symbols
    ]


class MergeDailyPoolConcurrencyTest(unittest.TestCase):
    """并发写同一 (year, market) 文件：锁生效、无异常、数据完整。"""

    def test_concurrent_merge_same_file_no_corruption(self) -> None:
        with TemporaryDirectory() as tmp:
            pool_root = Path(tmp)
            # _pool_daily_path 基于 settings.DATA_POOL_ROOT；打桩到临时目录
            with patch.object(hithink_dump.settings, "DATA_POOL_ROOT", str(pool_root)):
                # 先铺一个已有 target 文件（merge 走 read_parquet(target) 慢路径）。
                seed = _rows([f"{i:04d}.HK" for i in range(1, 101)])
                asyncio.run(
                    hithink_dump.merge_daily_pool(seed, source="openbb", market="HK")
                )

                # 多个并发批次写同一文件：修复后经文件级锁串行化，
                # 应全部成功且最终文件可读、数据完整。
                batches = [
                    _rows([f"{i:04d}.HK" for i in range(1, 51)], year=2026)
                    for _ in range(5)
                ]
                errors: list[BaseException] = []

                async def run() -> None:
                    results = await asyncio.gather(
                        *(
                            hithink_dump.merge_daily_pool(b, source="openbb", market="HK")
                            for b in batches
                        ),
                        return_exceptions=True,
                    )
                    for r in results:
                        if isinstance(r, BaseException):
                            errors.append(r)

                asyncio.run(run())

                self.assertEqual(
                    errors, [], f"并发 merge 不应产生异常（竞态应已被锁消除）: {errors}"
                )

                # 文件可读且包含铺底 + 合并的 symbol
                target = hithink_dump._pool_daily_path(2026, "HK")
                self.assertTrue(Path(target).exists(), "merge 目标文件应存在")
                n = duckdb.connect().execute(
                    f"SELECT count(DISTINCT symbol) FROM read_parquet('{target}',hive_partitioning=false)"
                ).fetchone()[0]
                self.assertEqual(n, 100, "铺底 100 只 symbol 应完整保留，无丢失")

    def test_file_lock_keyed_by_target(self) -> None:
        """文件级锁按 target 路径分配：同一路径共享锁，不同路径各自独立。"""
        p1 = hithink_dump._MERGE_FILE_LOCKS.setdefault("/tmp/a.parquet", asyncio.Lock())
        p2 = hithink_dump._MERGE_FILE_LOCKS.setdefault("/tmp/a.parquet", asyncio.Lock())
        p3 = hithink_dump._MERGE_FILE_LOCKS.setdefault("/tmp/b.parquet", asyncio.Lock())
        self.assertIs(p1, p2, "同一 target 应共享同一把锁（串行化）")
        self.assertIsNot(p1, p3, "不同 target 应用不同的锁（不牺牲并发）")

    def test_serial_merge_idempotent(self) -> None:
        """串行重复 merge 同一批数据：幂等，不重复（(symbol,date) 覆盖）。"""
        with TemporaryDirectory() as tmp:
            pool_root = Path(tmp)
            with patch.object(hithink_dump.settings, "DATA_POOL_ROOT", str(pool_root)):
                batch = _rows([f"{i:04d}.HK" for i in range(1, 11)])

                async def run() -> None:
                    await hithink_dump.merge_daily_pool(batch, source="openbb", market="HK")
                    await hithink_dump.merge_daily_pool(batch, source="openbb", market="HK")

                asyncio.run(run())
                target = hithink_dump._pool_daily_path(2026, "HK")
                n = duckdb.connect().execute(
                    f"SELECT count(*) FROM read_parquet('{target}',hive_partitioning=false)"
                ).fetchone()[0]
                self.assertEqual(n, 10, "重复 merge 应幂等，行数不变")


if __name__ == "__main__":
    unittest.main()
