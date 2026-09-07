from __future__ import annotations

import unittest
from datetime import date
from unittest.mock import AsyncMock, patch

from app.jobs import minute_kline


class RunMinuteKlineJobTest(unittest.IsolatedAsyncioTestCase):
    async def _run_scenario(
        self,
        days: list[date],
        sync_side_effect,
    ) -> tuple[dict[str, int], AsyncMock]:
        markers: dict[tuple[str, date], dict] = {}

        async def expected_days(market: str, through: date) -> list[date]:
            del through
            if market != "CN":
                return []
            return [
                trade_day
                for trade_day in days
                if not markers.get((market, trade_day), {}).get("complete")
            ]

        async def sync_day(market: str, symbols: list[str], trade_day: date) -> int:
            return await sync_side_effect(markers, market, symbols, trade_day)

        sync_mock = AsyncMock(side_effect=sync_day)
        with (
            patch.object(
                minute_kline,
                "_active_symbols",
                AsyncMock(return_value=["000001.SZ"]),
            ),
            patch.object(minute_kline, "_expected_days", side_effect=expected_days),
            patch.object(minute_kline, "_sync_day", sync_mock),
            patch.object(
                minute_kline,
                "delta_path",
                side_effect=lambda market, trade_day: (market, trade_day),
            ),
            patch.object(
                minute_kline,
                "read_delta_marker",
                side_effect=lambda path: markers.get(path),
            ),
        ):
            with patch.object(minute_kline, "datetime") as mocked_datetime:
                mocked_datetime.now.return_value.date.return_value = max(days)
                result = await minute_kline.run_minute_kline_job()
        return result, sync_mock

    async def test_one_run_catches_up_all_missing_days(self) -> None:
        days = [date(2026, 9, 3), date(2026, 9, 4)]

        async def complete(markers, market, symbols, trade_day):
            del symbols
            markers[(market, trade_day)] = {
                "complete": True,
                "covered_symbols": 1,
            }
            return 10

        result, sync_mock = await self._run_scenario(days, complete)

        self.assertEqual(result, {"CN": 20, "HK": 0, "US": 0})
        self.assertEqual(sync_mock.await_count, 2)

    async def test_partial_day_keeps_running_while_coverage_grows(self) -> None:
        days = [date(2026, 9, 4)]
        attempts = 0

        async def progress(markers, market, symbols, trade_day):
            nonlocal attempts
            del symbols
            attempts += 1
            markers[(market, trade_day)] = {
                "complete": attempts == 2,
                "covered_symbols": attempts,
            }
            return 10

        result, sync_mock = await self._run_scenario(days, progress)

        self.assertEqual(result, {"CN": 20, "HK": 0, "US": 0})
        self.assertEqual(sync_mock.await_count, 2)

    async def test_new_gap_discovered_during_run_is_also_synced(self) -> None:
        first_day = date(2026, 9, 3)
        discovered_day = date(2026, 9, 4)
        markers: dict[tuple[str, date], dict] = {}
        scans = 0

        async def expected_days(market: str, through: date) -> list[date]:
            nonlocal scans
            del through
            if market != "CN":
                return []
            scans += 1
            known_days = [first_day] if scans == 1 else [first_day, discovered_day]
            return [
                trade_day
                for trade_day in known_days
                if not markers.get((market, trade_day), {}).get("complete")
            ]

        async def complete(market: str, symbols: list[str], trade_day: date) -> int:
            del symbols
            markers[(market, trade_day)] = {
                "complete": True,
                "covered_symbols": 1,
            }
            return 10

        sync_mock = AsyncMock(side_effect=complete)
        with (
            patch.object(
                minute_kline,
                "_active_symbols",
                AsyncMock(return_value=["000001.SZ"]),
            ),
            patch.object(minute_kline, "_expected_days", side_effect=expected_days),
            patch.object(minute_kline, "_sync_day", sync_mock),
            patch.object(
                minute_kline,
                "delta_path",
                side_effect=lambda market, trade_day: (market, trade_day),
            ),
            patch.object(
                minute_kline,
                "read_delta_marker",
                side_effect=lambda path: markers.get(path),
            ),
        ):
            result = await minute_kline.run_minute_kline_job(day=discovered_day)

        self.assertEqual(result, {"CN": 20, "HK": 0, "US": 0})
        self.assertEqual(
            [call.args[2] for call in sync_mock.await_args_list],
            [first_day, discovered_day],
        )

    async def test_stalled_day_does_not_block_other_days(self) -> None:
        stalled_day = date(2026, 9, 3)
        completed_day = date(2026, 9, 4)

        async def mixed(markers, market, symbols, trade_day):
            del symbols
            if trade_day == completed_day:
                markers[(market, trade_day)] = {
                    "complete": True,
                    "covered_symbols": 1,
                }
                return 10
            return 0

        result, sync_mock = await self._run_scenario(
            [stalled_day, completed_day], mixed
        )

        self.assertEqual(
            result,
            {"CN": 10, "HK": 0, "US": 0, "incomplete_days": -1},
        )
        self.assertEqual(sync_mock.await_count, 2)

    async def test_explicit_day_catches_up_through_requested_date(self) -> None:
        earlier_day = date(2026, 9, 3)
        requested_day = date(2026, 9, 4)
        markers: dict[tuple[str, date], dict] = {}

        async def expected_days(market: str, through: date) -> list[date]:
            del through
            if market != "CN":
                return []
            return [
                trade_day
                for trade_day in (earlier_day, requested_day)
                if not markers.get((market, trade_day), {}).get("complete")
            ]

        async def complete(market: str, symbols: list[str], trade_day: date) -> int:
            del symbols
            markers[(market, trade_day)] = {
                "complete": True,
                "covered_symbols": 1,
            }
            return 10

        sync_mock = AsyncMock(side_effect=complete)
        with (
            patch.object(
                minute_kline,
                "_active_symbols",
                AsyncMock(return_value=["000001.SZ"]),
            ),
            patch.object(minute_kline, "_expected_days", side_effect=expected_days),
            patch.object(minute_kline, "_sync_day", sync_mock),
            patch.object(
                minute_kline,
                "delta_path",
                side_effect=lambda market, trade_day: (market, trade_day),
            ),
            patch.object(
                minute_kline,
                "read_delta_marker",
                side_effect=lambda path: markers.get(path),
            ),
        ):
            result = await minute_kline.run_minute_kline_job(day=requested_day)

        self.assertEqual(result, {"CN": 20, "HK": 0, "US": 0})
        self.assertEqual(sync_mock.await_count, 2)
        self.assertEqual(
            [call.args[2] for call in sync_mock.await_args_list],
            [earlier_day, requested_day],
        )


if __name__ == "__main__":
    unittest.main()
