"""分钟缓存内部空洞、原子覆盖发布与并发写入回归。"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
import multiprocessing
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import polars as pl
import pyarrow.parquet as pq

from app.config import settings
from app.data import client_minute as cache
from app.data.client import MinuteBarsResult
from app.data import minute_coverage
from test_minute_client_coverage import bar


def fetched(symbol, start, end, rows=None, complete=True):
    if rows is None:
        rows = [
            bar(symbol, day.isoformat()) for day in minute_coverage.dates(start, end)
        ]
    return MinuteBarsResult(rows, {symbol: [(start, end)]} if complete else {})


def process_writer(root, day, gate):
    settings.QUANT_CACHE_DIR = root

    async def source(symbols, start, end):
        await asyncio.sleep(0.03)
        return fetched(symbols[0], start, end)

    gate.wait(10)
    with mock.patch.object(
        cache, "fetch_minute_bars_with_coverage", side_effect=source
    ):
        cache.get_minute_bars_sync(
            ["AAPL"], date.fromisoformat(day), date.fromisoformat(day)
        )


def process_lock_holder(root, ready):
    from app.data.minute_coverage import locked_cache_sync

    settings.QUANT_CACHE_DIR = root
    with locked_cache_sync(cache._file_of("AAPL", 2026)):
        ready.set()
        import time

        time.sleep(30)


class MinuteCacheCoverageTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = mock.patch.object(settings, "QUANT_CACHE_DIR", self.tmp.name)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.d1, self.d2, self.d3 = date(2026, 1, 2), date(2026, 1, 3), date(2026, 1, 4)

    async def get(self, start, end=None, **kwargs):
        return await cache.get_minute_bars(["AAPL"], start, end or start, **kwargs)

    async def test_separate_windows_fill_real_interior_gap(self):
        async def source(symbols, start, end):
            return fetched(symbols[0], start, end)

        with mock.patch.object(
            cache, "fetch_minute_bars_with_coverage", side_effect=source
        ) as fetch:
            await self.get(self.d1)
            await self.get(self.d3)
            result = await self.get(self.d1, self.d3)
            self.assertEqual(result["AAPL"].height, 3)
            self.assertEqual(
                fetch.call_args_list[-1], mock.call(["AAPL"], self.d2, self.d2)
            )
            await self.get(self.d1, self.d3)
            self.assertEqual(fetch.await_count, 3)

    async def test_legacy_rows_are_preserved_but_unverified(self):
        legacy = cache.minute_bars_to_frame(
            [bar(day=self.d1.isoformat()), bar(day=self.d3.isoformat())]
        )
        cache.save_minute("AAPL", 2026, legacy)
        self.assertEqual(cache.load_minute("AAPL", 2026).height, 2)
        self.assertEqual(
            cache.missing_minute_ranges(legacy, self.d1, self.d3), [(self.d1, self.d3)]
        )
        with mock.patch.object(
            cache,
            "fetch_minute_bars_with_coverage",
            return_value=fetched("AAPL", self.d2, self.d2),
        ) as fetch:
            result = await self.get(self.d2)
        self.assertEqual(result["AAPL"].height, 1)
        self.assertEqual(fetch.await_count, 1)
        self.assertEqual(cache.load_minute("AAPL", 2026).height, 3)
        self.assertEqual(cache._load_minute_state("AAPL", 2026)[1], {self.d2})

    async def test_empty_holiday_is_negative_cached_and_expires(self):
        with mock.patch.object(
            cache,
            "fetch_minute_bars_with_coverage",
            return_value=fetched("AAPL", self.d1, self.d1, []),
        ) as fetch:
            self.assertEqual(await self.get(self.d1), {})
            self.assertEqual(await self.get(self.d1), {})
            self.assertEqual(fetch.await_count, 1)
            with mock.patch(
                "app.data.minute_coverage.utc_today",
                return_value=date.today() + timedelta(days=1),
            ):
                await self.get(self.d1)
            self.assertEqual(fetch.await_count, 2)
        self.assertTrue(cache._file_of("AAPL", 2026).exists())

    async def test_partial_failure_covers_only_successful_days(self):
        result = MinuteBarsResult(
            [bar(day=self.d1.isoformat())], {"AAPL": [(self.d1, self.d1)]}
        )
        with mock.patch.object(
            cache, "fetch_minute_bars_with_coverage", return_value=result
        ) as fetch:
            await self.get(self.d1, self.d3)
            await self.get(self.d1, self.d3)
        self.assertEqual(
            fetch.call_args_list[-1], mock.call(["AAPL"], self.d2, self.d3)
        )
        self.assertEqual(cache._load_minute_state("AAPL", 2026)[1], {self.d1})

    async def test_failed_empty_response_never_registers_coverage(self):
        with mock.patch.object(
            cache, "fetch_minute_bars_with_coverage", return_value=MinuteBarsResult()
        ) as fetch:
            await self.get(self.d1)
            await self.get(self.d1)
        self.assertEqual(fetch.await_count, 2)
        self.assertFalse(cache._file_of("AAPL", 2026).exists())

    async def test_single_day_truncation_remains_retryable(self):
        with mock.patch.object(
            cache,
            "fetch_minute_bars_with_coverage",
            return_value=fetched("AAPL", self.d1, self.d1, complete=False),
        ) as fetch:
            first = await self.get(self.d1)
            repeat = await self.get(self.d1)
        self.assertEqual(first["AAPL"].height, 1)
        self.assertEqual(repeat["AAPL"].height, 1)
        self.assertEqual(fetch.await_count, 2)
        self.assertEqual(cache._load_minute_state("AAPL", 2026)[1], set())

    async def test_refresh_preserves_outside_window_and_failure_old_data(self):
        async def source(symbols, start, end):
            return fetched(symbols[0], start, end)

        with mock.patch.object(
            cache, "fetch_minute_bars_with_coverage", side_effect=source
        ):
            await self.get(self.d1, self.d3)
        with mock.patch.object(
            cache,
            "fetch_minute_bars_with_coverage",
            return_value=fetched(
                "AAPL", self.d2, self.d2, [bar(day=self.d2.isoformat(), close=20)]
            ),
        ):
            result = await self.get(self.d2, use_cache=False)
        self.assertEqual(result["AAPL"]["close"][0], 20)
        self.assertEqual(cache.load_minute("AAPL", 2026).height, 3)
        with mock.patch.object(
            cache, "fetch_minute_bars_with_coverage", return_value=MinuteBarsResult()
        ):
            self.assertEqual(await self.get(self.d2, use_cache=False), {})
        self.assertEqual(cache.load_minute("AAPL", 2026).height, 3)
        with mock.patch.object(
            cache,
            "fetch_minute_bars_with_coverage",
            return_value=fetched("AAPL", self.d2, self.d2, []),
        ):
            await self.get(self.d2, use_cache=False)
        self.assertEqual(cache.load_minute("AAPL", 2026).height, 2)

    async def test_complete_revalidation_removes_legacy_stale_keys(self):
        rows = [bar(day=self.d1.isoformat()), bar(day=self.d1.isoformat())]
        rows[1]["datetime"] = self.d1.isoformat() + "T09:31:00"
        cache.save_minute("AAPL", 2026, cache.minute_bars_to_frame(rows))
        with mock.patch.object(
            cache,
            "fetch_minute_bars_with_coverage",
            return_value=fetched("AAPL", self.d1, self.d1),
        ):
            result = await self.get(self.d1)
        self.assertEqual(result["AAPL"].height, 1)
        self.assertEqual(cache.load_minute("AAPL", 2026).height, 1)

    async def test_complete_empty_revalidation_removes_legacy_window(self):
        cache.save_minute(
            "AAPL",
            2026,
            cache.minute_bars_to_frame(
                [bar(day=self.d1.isoformat()), bar(day=self.d3.isoformat())]
            ),
        )
        with mock.patch.object(
            cache,
            "fetch_minute_bars_with_coverage",
            return_value=fetched("AAPL", self.d1, self.d1, []),
        ) as fetch:
            self.assertEqual(await self.get(self.d1), {})
            self.assertEqual(await self.get(self.d1), {})
        self.assertEqual(fetch.await_count, 1)
        self.assertEqual(cache.load_minute("AAPL", 2026).height, 1)
        self.assertEqual(cache.load_minute("AAPL", 2026)["datetime"][0].date(), self.d3)

    async def test_failed_refresh_revokes_old_proof_preserves_old_rows(self):
        with mock.patch.object(
            cache,
            "fetch_minute_bars_with_coverage",
            return_value=fetched("AAPL", self.d1, self.d1),
        ):
            await self.get(self.d1)
        with mock.patch.object(
            cache, "fetch_minute_bars_with_coverage", return_value=MinuteBarsResult()
        ) as fetch:
            self.assertEqual(await self.get(self.d1, use_cache=False), {})
            self.assertEqual(cache._load_minute_state("AAPL", 2026)[1], set())
            fallback = await self.get(self.d1)
        self.assertEqual(fallback["AAPL"].height, 1)
        self.assertEqual(fetch.await_count, 2)

    async def test_truncated_refresh_revokes_old_proof(self):
        with mock.patch.object(
            cache,
            "fetch_minute_bars_with_coverage",
            return_value=fetched("AAPL", self.d1, self.d1),
        ):
            await self.get(self.d1)
        with mock.patch.object(
            cache,
            "fetch_minute_bars_with_coverage",
            return_value=fetched("AAPL", self.d1, self.d1, complete=False),
        ) as fetch:
            await self.get(self.d1, use_cache=False)
            self.assertEqual(cache._load_minute_state("AAPL", 2026)[1], set())
            await self.get(self.d1)
        self.assertEqual(fetch.await_count, 2)

    async def test_fetch_timeout_releases_lock_and_preserves_rows(self):
        async def stuck_source(*args):
            await asyncio.sleep(10)

        with mock.patch.object(
            cache, "fetch_minute_bars_with_coverage", side_effect=stuck_source
        ):
            with mock.patch.object(cache, "_FETCH_TIMEOUT_SECONDS", 0.01):
                self.assertEqual(await self.get(self.d1), {})
        with mock.patch.object(
            cache,
            "fetch_minute_bars_with_coverage",
            return_value=fetched("AAPL", self.d1, self.d1),
        ):
            await asyncio.wait_for(self.get(self.d1), 1)

    async def test_async_lock_wait_is_bounded(self):
        async with minute_coverage.locked_cache(cache._file_of("AAPL", 2026)):
            with mock.patch.object(minute_coverage, "_LOCK_TIMEOUT_SECONDS", 0.01):
                self.assertEqual(await self.get(self.d1), {})

    async def test_cancelled_refresh_revokes_old_proof_before_http(self):
        with mock.patch.object(
            cache,
            "fetch_minute_bars_with_coverage",
            return_value=fetched("AAPL", self.d1, self.d1),
        ):
            await self.get(self.d1)
        with mock.patch.object(
            cache, "fetch_minute_bars_with_coverage", side_effect=asyncio.CancelledError
        ):
            with self.assertRaises(asyncio.CancelledError):
                await self.get(self.d1, use_cache=False)
        saved, covered = cache._load_minute_state("AAPL", 2026)
        self.assertEqual(saved.height, 1)
        self.assertEqual(covered, set())

    async def test_failed_invalidation_aborts_refresh_preserving_old_snapshot(self):
        with mock.patch.object(
            cache,
            "fetch_minute_bars_with_coverage",
            return_value=fetched("AAPL", self.d1, self.d1),
        ):
            await self.get(self.d1)
        before = cache._file_of("AAPL", 2026).read_bytes()
        with mock.patch.object(cache, "fetch_minute_bars_with_coverage") as fetch:
            with mock.patch.object(
                cache.os, "replace", side_effect=OSError("disk full")
            ):
                self.assertEqual(await self.get(self.d1, use_cache=False), {})
        self.assertEqual(fetch.await_count, 0)
        self.assertEqual(cache._file_of("AAPL", 2026).read_bytes(), before)

    async def test_lock_timeout_returns_available_old_rows(self):
        cache.save_minute(
            "AAPL", 2026, cache.minute_bars_to_frame([bar(day=self.d1.isoformat())])
        )
        async with minute_coverage.locked_cache(cache._file_of("AAPL", 2026)):
            with mock.patch.object(minute_coverage, "_LOCK_TIMEOUT_SECONDS", 0.01):
                result = await self.get(self.d1)
        self.assertEqual(result["AAPL"].height, 1)

    async def test_partial_refresh_retains_old_failed_child_and_revokes_proof(self):
        async def source(symbols, start, end):
            return fetched(symbols[0], start, end)

        with mock.patch.object(
            cache, "fetch_minute_bars_with_coverage", side_effect=source
        ):
            await self.get(self.d1, self.d3)
        partial = MinuteBarsResult(
            [bar(day=self.d1.isoformat(), close=20)], {"AAPL": [(self.d1, self.d1)]}
        )
        with mock.patch.object(
            cache, "fetch_minute_bars_with_coverage", return_value=partial
        ):
            result = await self.get(self.d1, self.d3, use_cache=False)
        self.assertEqual(result["AAPL"].height, 1)
        saved, covered = cache._load_minute_state("AAPL", 2026)
        self.assertEqual(saved.height, 3)
        self.assertEqual(saved["close"].to_list(), [20.0, 10.0, 10.0])
        self.assertEqual(covered, {self.d1})

    async def test_atomic_publish_keeps_worker_read_permissions(self):
        import stat

        with mock.patch.object(
            cache,
            "fetch_minute_bars_with_coverage",
            return_value=fetched("AAPL", self.d1, self.d1),
        ):
            await self.get(self.d1)
        path = cache._file_of("AAPL", 2026)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o644)
        path.chmod(0o640)
        with mock.patch.object(
            cache,
            "fetch_minute_bars_with_coverage",
            return_value=fetched("AAPL", self.d3, self.d3),
        ):
            await self.get(self.d3)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o640)

    async def test_save_minute_external_rewrite_revokes_coverage(self):
        with mock.patch.object(
            cache,
            "fetch_minute_bars_with_coverage",
            return_value=fetched("AAPL", self.d1, self.d1),
        ):
            await self.get(self.d1)
        cache.save_minute("AAPL", 2026, cache.load_minute("AAPL", 2026))
        self.assertEqual(cache._load_minute_state("AAPL", 2026)[1], set())

    def test_dead_process_releases_flock(self):
        context = multiprocessing.get_context("spawn")
        ready = context.Event()
        holder = context.Process(
            target=process_lock_holder, args=(self.tmp.name, ready)
        )
        holder.start()
        try:
            self.assertTrue(ready.wait(10))
        finally:
            holder.kill()
            holder.join(10)
        with minute_coverage.locked_cache_sync(cache._file_of("AAPL", 2026)):
            pass

    async def test_utc_rollover_invalidation_does_not_depend_on_host_timezone(self):
        day = date(2026, 11, 6)
        with mock.patch.object(
            cache,
            "fetch_minute_bars_with_coverage",
            return_value=fetched("AAPL", day, day),
        ) as fetch:
            with mock.patch.object(cache, "utc_today", return_value=day):
                await self.get(day)
                self.assertEqual(cache._load_minute_state("AAPL", 2026)[1], set())
            with mock.patch.object(
                cache, "utc_today", return_value=day + timedelta(days=1)
            ):
                await self.get(day)
                await self.get(day)
            self.assertEqual(fetch.await_count, 2)

    async def test_write_failure_preserves_data_and_coverage_snapshot(self):
        with mock.patch.object(
            cache,
            "fetch_minute_bars_with_coverage",
            return_value=fetched("AAPL", self.d1, self.d1),
        ):
            await self.get(self.d1)
        before = cache._file_of("AAPL", 2026).read_bytes()
        with mock.patch.object(
            cache,
            "fetch_minute_bars_with_coverage",
            return_value=fetched("AAPL", self.d2, self.d2),
        ):
            with mock.patch.object(
                cache.os, "replace", side_effect=OSError("disk full")
            ):
                result = await self.get(self.d2)
        self.assertEqual(result["AAPL"].height, 1)
        self.assertEqual(cache._file_of("AAPL", 2026).read_bytes(), before)
        self.assertEqual(cache._load_minute_state("AAPL", 2026)[1], {self.d1})
        self.assertEqual(list(Path(self.tmp.name).rglob("*.tmp.*")), [])

    async def test_corrupt_cache_and_bad_metadata_refetch(self):
        path = cache._file_of("AAPL", 2026)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"invalid parquet")
        self.assertTrue(cache.load_minute("AAPL", 2026).is_empty())
        with mock.patch.object(
            cache,
            "fetch_minute_bars_with_coverage",
            return_value=fetched("AAPL", self.d1, self.d1),
        ) as fetch:
            await self.get(self.d1)
            table = pq.read_table(path, partitioning=None).replace_schema_metadata(
                {minute_coverage._METADATA_KEY: b"broken json"}
            )
            pq.write_table(table, path)
            await self.get(self.d1)
        self.assertEqual(fetch.await_count, 2)

    async def test_concurrent_identical_request_fetches_once(self):
        async def source(symbols, start, end):
            await asyncio.sleep(0.03)
            return fetched(symbols[0], start, end)

        with mock.patch.object(
            cache, "fetch_minute_bars_with_coverage", side_effect=source
        ) as fetch:
            results = await asyncio.gather(self.get(self.d1), self.get(self.d1))
        self.assertEqual(fetch.await_count, 1)
        self.assertTrue(results[0]["AAPL"].equals(results[1]["AAPL"]))

    async def test_concurrent_disjoint_request_preserves_both_windows(self):
        async def source(symbols, start, end):
            await asyncio.sleep(0.03)
            return fetched(symbols[0], start, end)

        with mock.patch.object(
            cache, "fetch_minute_bars_with_coverage", side_effect=source
        ):
            await asyncio.gather(self.get(self.d1), self.get(self.d3))
        self.assertEqual(cache.load_minute("AAPL", 2026).height, 2)
        self.assertEqual(cache._load_minute_state("AAPL", 2026)[1], {self.d1, self.d3})

    async def test_cancelled_lock_wait_and_fetch_release_lock(self):
        async with minute_coverage.locked_cache(cache._file_of("AAPL", 2026)):
            waiter = asyncio.create_task(self.get(self.d1))
            await asyncio.sleep(0.01)
            waiter.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await waiter
        with mock.patch.object(
            cache, "fetch_minute_bars_with_coverage", side_effect=asyncio.CancelledError
        ):
            with self.assertRaises(asyncio.CancelledError):
                await self.get(self.d1)
        with mock.patch.object(
            cache,
            "fetch_minute_bars_with_coverage",
            return_value=fetched("AAPL", self.d1, self.d1),
        ):
            await asyncio.wait_for(self.get(self.d1), 1)

    async def test_cross_year_requests_reuse_each_year_ledger(self):
        async def source(symbols, start, end):
            return fetched(symbols[0], start, end)

        with mock.patch.object(
            cache, "fetch_minute_bars_with_coverage", side_effect=source
        ) as fetch:
            result = await self.get(date(2025, 12, 31), date(2026, 1, 2))
            await self.get(date(2025, 12, 31), date(2026, 1, 2))
        self.assertEqual(result["AAPL"].height, 3)
        self.assertEqual(fetch.await_count, 2)
        self.assertEqual(len(list(Path(self.tmp.name).rglob("*.parquet"))), 2)

    async def test_current_day_is_not_permanently_covered(self):
        today = date.today()
        with mock.patch.object(
            cache,
            "fetch_minute_bars_with_coverage",
            return_value=fetched("AAPL", today, today),
        ) as fetch:
            await self.get(today)
            await self.get(today)
        self.assertEqual(fetch.await_count, 2)

    def test_sync_threads_and_processes_preserve_disjoint_writes(self):
        async def source(symbols, start, end):
            await asyncio.sleep(0.02)
            return fetched(symbols[0], start, end)

        with mock.patch.object(
            cache, "fetch_minute_bars_with_coverage", side_effect=source
        ):
            with ThreadPoolExecutor(max_workers=2) as pool:
                jobs = [
                    pool.submit(cache.get_minute_bars_sync, ["AAPL"], day, day)
                    for day in (self.d1, self.d3)
                ]
                for job in jobs:
                    self.assertEqual(job.result(timeout=5)["AAPL"].height, 1)
        context = multiprocessing.get_context("spawn")
        gate = context.Event()
        processes = [
            context.Process(
                target=process_writer, args=(self.tmp.name, day.isoformat(), gate)
            )
            for day in (date(2026, 1, 5), date(2026, 1, 6))
        ]
        for process in processes:
            process.start()
        gate.set()
        for process in processes:
            process.join(10)
            if process.is_alive():
                process.kill()
                process.join()
            self.assertEqual(process.exitcode, 0)
        self.assertEqual(cache.load_minute("AAPL", 2026).height, 4)
        self.assertEqual(len(cache._load_minute_state("AAPL", 2026)[1]), 4)
        self.assertEqual(list(Path(self.tmp.name).rglob("*.tmp.*")), [])


if __name__ == "__main__":
    unittest.main()
