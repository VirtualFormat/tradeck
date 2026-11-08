"""分钟客户端覆盖与降级回归：全部使用 MockTransport，测试容器禁网。"""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
import unittest
from unittest import mock

import httpx

from app.data import client


def bar(symbol="AAPL", day="2026-01-02", close=10.0):
    return {
        "symbol": symbol,
        "datetime": day + "T09:30:00",
        "open": close,
        "high": close,
        "low": close,
        "close": close,
        "volume": 1.0,
        "amount": None,
        "source": "test",
    }


def response(rows=(), truncated=False):
    return httpx.Response(
        200,
        json={
            "bars": list(rows),
            "count": len(rows),
            "truncated": truncated,
            "source": "cold",
        },
    )


class MinuteClientCoverageTests(unittest.IsolatedAsyncioTestCase):
    async def test_transport_and_bad_response_retry_exhaustion(self):
        for failure in (
            httpx.ReadError,
            httpx.RemoteProtocolError,
            httpx.ConnectError,
            httpx.ReadTimeout,
            "json",
            "schema",
            "count",
            "wrong_day",
        ):
            with self.subTest(failure=failure):
                attempts = []

                def handler(request):
                    attempts.append(request)
                    if failure == "json":
                        return httpx.Response(200, text="bad JSON")
                    if failure == "schema":
                        return httpx.Response(200, json={"bars": []})
                    if failure == "count":
                        return httpx.Response(
                            200, json={"bars": [], "count": 1, "truncated": False}
                        )
                    if failure == "wrong_day":
                        return response([bar(day="2025-12-31")])
                    raise failure("simulated", request=request)

                with mock.patch(
                    "app.data.client.asyncio.sleep", new_callable=mock.AsyncMock
                ) as sleep:
                    async with httpx.AsyncClient(
                        transport=httpx.MockTransport(handler)
                    ) as http:
                        result = await client.fetch_minute_bars_with_coverage(
                            ["AAPL"],
                            date(2026, 1, 2),
                            date(2026, 1, 2),
                            http_client=http,
                        )
                self.assertEqual(result.bars, [])
                self.assertEqual(result.covered_ranges, {})
                self.assertEqual(len(attempts), 4)
                self.assertEqual(
                    sleep.call_args_list, [mock.call(1), mock.call(2), mock.call(4)]
                )

    async def test_datetime_nan_duplicate_and_ohlcv_schema_are_rejected(self):
        mutations = [
            {"datetime": None},
            {"datetime": 123},
            {"datetime": "2026-01-02"},
            {"datetime": "2026-01-02T09:30:00+08:00"},
            {"datetime": "2026-01-02T09:30:01"},
            {"datetime": "invalid"},
            {"open": float("nan")},
            {"volume": float("inf")},
            {"close": "10.0"},
            {"amount": True},
            {"source": {}},
            {"low": 11},
            {"high": 9},
            {"volume": -1},
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                invalid = {**bar(), **mutation}
                with self.assertRaises((ValueError, TypeError)):
                    client._validate_minute_response(
                        {"bars": [invalid], "count": 1, "truncated": False},
                        ["AAPL"],
                        date(2026, 1, 2),
                        date(2026, 1, 2),
                    )
        rows = [bar(), bar()]
        rows[1]["datetime"] = "2026-01-02 09:30:00"
        with self.assertRaises(ValueError):
            client._validate_minute_response(
                {"bars": rows, "count": 2, "truncated": False},
                ["AAPL"],
                date(2026, 1, 2),
                date(2026, 1, 2),
            )
        missing_amount = bar()
        del missing_amount["amount"]
        with self.assertRaises(KeyError):
            client._validate_minute_response(
                {"bars": [missing_amount], "count": 1, "truncated": False},
                ["AAPL"],
                date(2026, 1, 2),
                date(2026, 1, 2),
            )

    async def test_bad_row_response_is_retried_then_degrades_as_list(self):
        for mutation in ({"datetime": None}, {"open": float("nan")}, {"amount": "10"}):
            calls = []

            def handler(request):
                import json

                calls.append(request)
                body = {"bars": [{**bar(), **mutation}], "count": 1, "truncated": False}
                return httpx.Response(200, content=json.dumps(body))

            with mock.patch(
                "app.data.client.asyncio.sleep", new_callable=mock.AsyncMock
            ):
                async with httpx.AsyncClient(
                    transport=httpx.MockTransport(handler)
                ) as http:
                    rows = await client.fetch_minute_bars(
                        ["AAPL"], date(2026, 1, 2), date(2026, 1, 2), http_client=http
                    )
            self.assertIs(type(rows), list)
            self.assertEqual(rows, [])
            self.assertEqual(len(calls), 4)

    async def test_us_alias_float_volume_and_null_amount_preserve_contract(self):
        row = bar()
        row["volume"] = 10.25
        row["datetime"] = "2026-01-02 09:30:00"
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: response([row]))
        ) as http:
            result = await client.fetch_minute_bars_with_coverage(
                ["AAPL.US"], date(2026, 1, 2), date(2026, 1, 2), http_client=http
            )
        self.assertEqual(result.bars[0]["symbol"], "AAPL")
        self.assertEqual(result.bars[0]["datetime"], "2026-01-02T09:30:00")
        self.assertEqual(result.bars[0]["volume"], 10.25)
        self.assertIsNone(result.bars[0]["amount"])
        self.assertEqual(set(result.covered_ranges), {"AAPL.US"})

    async def test_retry_success_and_4xx_no_retry(self):
        for status in (401, 422, 503):
            attempts = []

            def handler(request):
                attempts.append(request)
                if len(attempts) == 1:
                    return httpx.Response(status, json={"detail": "simulated"})
                return response([bar()])

            with mock.patch(
                "app.data.client.asyncio.sleep", new_callable=mock.AsyncMock
            ):
                async with httpx.AsyncClient(
                    transport=httpx.MockTransport(handler)
                ) as http:
                    result = await client.fetch_minute_bars_with_coverage(
                        ["AAPL"], date(2026, 1, 2), date(2026, 1, 2), http_client=http
                    )
            self.assertEqual(len(attempts), 2 if status == 503 else 1)
            self.assertEqual(bool(result.covered_ranges), status == 503)

    async def test_partial_recursive_failure_only_covers_successful_child(self):
        def handler(request):
            import json

            body = json.loads(request.content)
            if body["start_date"] != body["end_date"]:
                return response([bar()], truncated=True)
            if body["start_date"] == "2026-01-03":
                return httpx.Response(422)
            return response([bar()])

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            result = await client.fetch_minute_bars_with_coverage(
                ["AAPL"], date(2026, 1, 2), date(2026, 1, 3), http_client=http
            )
        self.assertEqual(result.bars, [bar()])
        self.assertEqual(
            result.covered_ranges, {"AAPL": [(date(2026, 1, 2), date(2026, 1, 2))]}
        )

    async def test_single_day_truncation_splits_symbols_and_tracks_failure(self):
        def handler(request):
            import json

            body = json.loads(request.content)
            if len(body["symbols"]) > 1:
                return response([bar()], truncated=True)
            return response(
                [bar(body["symbols"][0])], truncated=body["symbols"] == ["MSFT"]
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            result = await client.fetch_minute_bars_with_coverage(
                ["AAPL", "MSFT"], date(2026, 1, 2), date(2026, 1, 2), http_client=http
            )
        self.assertEqual(len(result.bars), 2)
        self.assertEqual(set(result.covered_ranges), {"AAPL"})

    async def test_recursive_windows_are_globally_sorted(self):
        def handler(request):
            import json

            body = json.loads(request.content)
            if body["start_date"] != body["end_date"]:
                return response(truncated=True)
            return response(
                [bar("MSFT", body["start_date"]), bar("AAPL", body["start_date"])]
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            rows = await client.fetch_minute_bars(
                ["MSFT", "AAPL"], date(2026, 1, 2), date(2026, 1, 3), http_client=http
            )
        self.assertIs(type(rows), list)
        keys = [(row["symbol"], row["datetime"]) for row in rows]
        self.assertEqual(keys, sorted(keys))

    async def test_symbol_deduplication_window_and_chunk_limits(self):
        import json

        requests = []

        def handler(request):
            requests.append(json.loads(request.content))
            return response()

        symbols = [f"SYM{i}" for i in range(51)] + ["SYM0"]
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            result = await client.fetch_minute_bars_with_coverage(
                symbols, date(2025, 1, 1), date(2026, 1, 5), http_client=http
            )
        self.assertEqual([len(req["symbols"]) for req in requests], [50, 1, 50, 1])
        self.assertEqual(requests[2]["start_date"], "2026-01-03")
        self.assertEqual(len(result.covered_ranges), 51)
        self.assertEqual(len(result.covered_ranges["SYM0"]), 2)

    async def test_cancel_propagates(self):
        def handler(request):
            raise asyncio.CancelledError()

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            with self.assertRaises(asyncio.CancelledError):
                await client.fetch_minute_bars(
                    ["AAPL"], date(2026, 1, 2), date(2026, 1, 2), http_client=http
                )

    async def test_get_transport_and_json_failures_degrade(self):
        for failure in (httpx.ReadError, "json"):

            def handler(request):
                if failure == "json":
                    return httpx.Response(200, text="invalid")
                raise failure("simulated", request=request)

            http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
            with mock.patch("app.data.client.httpx.AsyncClient", return_value=http):
                self.assertIsNone(await client.get_json("/api/bars/minute", {}))


if __name__ == "__main__":
    unittest.main()
