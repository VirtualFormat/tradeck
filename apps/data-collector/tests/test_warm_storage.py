"""warm_storage 单测：纯标准库 unittest + 打桩，不起真 ClickHouse。

覆盖：
- JSONEachRow 序列化（UTC ts 格式、NaN 拒收、volume 转 int）
- replace_market_day 的「删+插」调用顺序与幂等语义
- 禁用 / 连接失败 / 插入失败三条降级路径（不抛异常、返回错误摘要）
"""
from __future__ import annotations

import json
import unittest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

from app.config import settings
from app.warm_storage import (
    ClickHouseClient,
    insert_market_day,
    minute_bars,
    replace_market_day,
    reset_warm_client,
    serialize_rows,
    write_minute_bars,
)


def _row(ts, **over):
    row = {
        "symbol": "000001.SZ",
        "market": "CN",
        "ts": ts,
        "open": 10.0,
        "high": 10.5,
        "low": 9.8,
        "close": 10.2,
        "volume": 12345.0,
        "amount": 125_000.0,
    }
    row.update(over)
    return row


class SerializeRowsTest(unittest.TestCase):
    """JSONEachRow 行序列化与防御性清洗。"""
    def test_naive_datetime_formatted_as_utc_string(self):
        rows, rejected = serialize_rows([_row(datetime(2026, 9, 7, 1, 30, 0))])
        self.assertEqual(rejected, 0)
        self.assertEqual(rows[0]["ts"], "2026-09-07 01:30:00")
        self.assertEqual(rows[0]["volume"], 12345)  # 转 int
        self.assertIsInstance(rows[0]["open"], float)

    def test_aware_datetime_converted_to_utc(self):
        # UTC+8 的 09:30 应转 UTC 01:30（纪律：ts 一律 UTC）
        tz_cn = timezone(timedelta(hours=8))
        rows, rejected = serialize_rows(
            [_row(datetime(2026, 9, 7, 9, 30, 0, tzinfo=tz_cn))]
        )
        self.assertEqual(rejected, 0)
        self.assertEqual(rows[0]["ts"], "2026-09-07 01:30:00")

    def test_string_ts_passthrough(self):
        rows, _ = serialize_rows([_row("2026-09-07 01:30:00")])
        self.assertEqual(rows[0]["ts"], "2026-09-07 01:30:00")

    def test_nan_row_rejected(self):
        rows, rejected = serialize_rows(
            [_row(datetime(2026, 9, 7), open=float("nan"))]
        )
        self.assertEqual(rows, [])
        self.assertEqual(rejected, 1)

    def test_inf_and_bad_volume_rejected(self):
        rows, rejected = serialize_rows(
            [
                _row(datetime(2026, 9, 7), close=float("inf")),
                _row(datetime(2026, 9, 7), volume="abc"),
            ]
        )
        self.assertEqual(rows, [])
        self.assertEqual(rejected, 2)

    def test_serialized_row_is_valid_json_each_row(self):
        rows, _ = serialize_rows([_row(datetime(2026, 9, 7, 1, 30))])
        line = json.dumps(rows[0], ensure_ascii=False)
        decoded = json.loads(line)
        self.assertEqual(
            list(decoded),
            ["symbol", "market", "ts", "open", "high", "low", "close", "volume", "amount"],
        )


class ReplaceMarketDayTest(unittest.IsolatedAsyncioTestCase):
    """幂等入口的删+插顺序与降级语义。"""

    async def test_mismatched_market_rows_rejected(self):
        """异市场行拒收：删除范围是 market+day，混入异市场行重跑会产生重复。"""
        client = AsyncMock(spec=ClickHouseClient)
        client.execute.return_value = True
        client.insert_json_each_row.return_value = True
        day = date(2026, 9, 7)
        cn = _row(datetime(2026, 9, 7, 1, 30))  # market=CN
        us = {**_row(datetime(2026, 9, 7, 13, 30)), "symbol": "AAPL", "market": "US"}

        written, err = await replace_market_day(client, "CN", day, [cn, us])

        # 只有 CN 行被插入，US 行被接口层拒收
        self.assertEqual(err, "")
        markets = {r["market"] for r in client.insert_json_each_row.call_args.args[1]}
        self.assertEqual(markets, {"CN"})
        self.assertEqual(written, 1)

    async def test_delete_then_insert_in_order(self):
        client = AsyncMock(spec=ClickHouseClient)
        client.execute.return_value = True
        client.insert_json_each_row.return_value = True
        day = date(2026, 9, 7)

        written, err = await replace_market_day(
            client, "CN", day, [_row(datetime(2026, 9, 7, 1, 30))]
        )

        self.assertEqual((written, err), (1, ""))
        # 顺序：先 ALTER DELETE 后 INSERT（删除先于插入被 await）
        self.assertEqual(client.method_calls[0][0], "execute")
        self.assertEqual(client.method_calls[1][0], "insert_json_each_row")
        # 删除 SQL 与参数符合契约（CH {name:Type} 占位符 + 日分区条件）
        (sql,) = client.execute.call_args.args
        self.assertIn("ALTER TABLE minute_bars DELETE", sql)
        self.assertIn("market = {m:String}", sql)
        self.assertIn("toDate(ts) = {d:Date}", sql)
        self.assertEqual(
            client.execute.call_args.kwargs["params"],
            {"m": "CN", "d": "2026-09-07"},
        )

    async def test_delete_failure_returns_error_and_skips_insert(self):
        client = AsyncMock(spec=ClickHouseClient)
        client.execute.return_value = False

        written, err = await replace_market_day(
            client, "CN", date(2026, 9, 7), [_row(datetime(2026, 9, 7))]
        )

        self.assertEqual(written, 0)
        self.assertIn("删除失败", err)
        client.insert_json_each_row.assert_not_called()

    async def test_insert_failure_returns_error(self):
        client = AsyncMock(spec=ClickHouseClient)
        client.execute.return_value = True
        client.insert_json_each_row.return_value = False

        written, err = await replace_market_day(
            client, "CN", date(2026, 9, 7), [_row(datetime(2026, 9, 7))]
        )

        self.assertEqual(written, 0)
        self.assertIn("插入失败", err)

    async def test_chunked_insert_splits_over_chunk_size(self):
        client = AsyncMock(spec=ClickHouseClient)
        client.insert_json_each_row.return_value = True
        rows = [{"symbol": "s"}] * (minute_bars.INSERT_CHUNK_SIZE + 1)

        written, err = await insert_market_day(client, rows)

        self.assertEqual((written, err), (len(rows), ""))
        self.assertEqual(client.insert_json_each_row.call_count, 2)
        sizes = [
            len(call.args[1]) for call in client.insert_json_each_row.call_args_list
        ]
        self.assertEqual(sizes, [minute_bars.INSERT_CHUNK_SIZE, 1])


class WriteMinuteBarsDegradationTest(unittest.IsolatedAsyncioTestCase):
    """三态优雅降级：禁用 / ping 失败 / 插入失败，均不抛异常。"""

    def setUp(self):
        reset_warm_client()
        self._enabled = settings.CLICKHOUSE_ENABLED

    def tearDown(self):
        settings.CLICKHOUSE_ENABLED = self._enabled
        reset_warm_client()

    async def test_disabled_returns_digest_without_touching_ch(self):
        settings.CLICKHOUSE_ENABLED = ""
        with patch("app.warm_storage.get_warm_client") as get_client:
            written, err = await write_minute_bars("CN", date(2026, 9, 7), [])
        self.assertEqual(written, 0)
        self.assertIn("CLICKHOUSE_ENABLED", err)
        get_client.assert_not_called()

    async def test_ping_failure_returns_digest(self):
        settings.CLICKHOUSE_ENABLED = "1"
        client = AsyncMock(spec=ClickHouseClient)
        client.ping.return_value = False
        with patch("app.warm_storage.get_warm_client", return_value=client):
            written, err = await write_minute_bars(
                "CN", date(2026, 9, 7), [_row(datetime(2026, 9, 7))]
            )
        self.assertEqual(written, 0)
        self.assertIn("ping", err)
        client.execute.assert_not_called()

    async def test_insert_failure_returns_digest(self):
        settings.CLICKHOUSE_ENABLED = "1"
        client = AsyncMock(spec=ClickHouseClient)
        client.ping.return_value = True
        client.execute.return_value = True
        client.insert_json_each_row.return_value = False
        with patch("app.warm_storage.get_warm_client", return_value=client):
            written, err = await write_minute_bars(
                "CN", date(2026, 9, 7), [_row(datetime(2026, 9, 7))]
            )
        self.assertEqual(written, 0)
        self.assertIn("插入失败", err)


class ClientHttpBehaviorTest(unittest.IsolatedAsyncioTestCase):
    """客户端传输层：请求形态、重试、异常不冒泡（打桩 httpx.AsyncClient）。"""

    def _client(self) -> ClickHouseClient:
        return ClickHouseClient("http://clickhouse:8123", "tradeck")

    async def test_insert_builds_json_each_row_request(self):
        captured = {}

        class FakeResp:
            status_code = 200
            text = ""

        class FakeSession:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def request(self, method, url, content=None, params=None):
                captured.update(
                    {"method": method, "url": url, "content": content, "params": params}
                )
                return FakeResp()

        # 传输层只吃已序列化行（序列化是 serialize_rows 的职责）
        rows, _ = serialize_rows([_row(datetime(2026, 9, 7, 1, 30))])
        client = self._client()
        with patch(
            "app.warm_storage.clickhouse_client.httpx.AsyncClient",
            return_value=FakeSession(),
        ):
            ok = await client.insert_json_each_row("minute_bars", rows)

        self.assertTrue(ok)
        self.assertEqual(captured["url"], "http://clickhouse:8123")
        self.assertEqual(
            captured["params"]["query"], "INSERT INTO minute_bars FORMAT JSONEachRow"
        )
        self.assertEqual(captured["params"]["database"], "tradeck")
        # body 为 JSONEachRow（每行一个 JSON，末尾换行）
        lines = captured["content"].decode("utf-8").splitlines()
        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0])["symbol"], "000001.SZ")

    async def test_network_exception_returns_false_not_raise(self):
        class BoomSession:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def request(self, *args, **kwargs):
                raise OSError("connection refused")

        client = self._client()
        with (
            patch(
                "app.warm_storage.clickhouse_client.httpx.AsyncClient",
                return_value=BoomSession(),
            ),
            patch(
                "app.warm_storage.clickhouse_client.asyncio.sleep",
                new=AsyncMock(),
            ) as sleep_mock,
        ):
            ok = await client.insert_json_each_row("minute_bars", [{"a": 1}])
            self.assertFalse(ok)
            # INSERT 允许 1 次重试 → 退避一次
            self.assertEqual(sleep_mock.await_count, 1)

            ok = await client.execute("ALTER TABLE t DELETE WHERE 1")
            self.assertFalse(ok)

            ok = await client.ping()
            self.assertFalse(ok)

    async def test_execute_uses_param_placeholders(self):
        captured = {}

        class FakeResp:
            status_code = 200
            text = ""

        class FakeSession:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def request(self, method, url, content=None, params=None):
                captured["params"] = params
                return FakeResp()

        client = self._client()
        with patch(
            "app.warm_storage.clickhouse_client.httpx.AsyncClient",
            return_value=FakeSession(),
        ):
            ok = await client.execute(
                "ALTER TABLE minute_bars DELETE WHERE market = {m:String}",
                params={"m": "CN"},
            )
        self.assertTrue(ok)
        self.assertEqual(captured["params"]["param_m"], "CN")
        self.assertEqual(captured["params"]["database"], "tradeck")


if __name__ == "__main__":
    unittest.main()
