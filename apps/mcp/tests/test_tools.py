"""工具层单测（经 ASGI 调 /mcp 的 JSON-RPC tools/call，api / quant 用 MockTransport 模拟）。

覆盖：身份透传（X-User-Id 只来自令牌）、scope 不足、调用配额 / 回测提交配额、入参校验
（universe=all、symbols 上限、id 形态、代码体积）、quant 4xx detail 透出与 5xx 通用文案、
task 404 文案、长轮询、summary ≤10KB 与分页、errors 端点 404 降级。
"""

from __future__ import annotations

import asyncio
import json
import unittest

import httpx2

from app.main import AUTH_TIMEOUT
from app.quant_client import QUANT_TIMEOUT, TASK_TIMEOUT
from app.tools import (
    MAX_WAIT_SECONDS,
    POLL_INTERVAL_SECONDS,
    TASK_NOT_FOUND_MESSAGE,
    TIMEOUT_MESSAGE,
    UNAVAILABLE_MESSAGE,
)
from tests._helpers import (
    SERVICE_TOKEN,
    TOKEN_BACKTEST,
    TOKEN_FULL,
    TOKEN_READONLY,
    McpHarness,
    make_settings,
)
from tests.test_results import big_position_result

TASK_ID = "0123456789abcdef0123456789abcdef"
STRATEGY_CODE = 'META = {"id": "my_strat", "name": "测试"}\n\ndef compute(enriched, params):\n    pass\n'


def _rpc_headers(token: str) -> dict:
    """手写原始 JSON-RPC 请求体时用的请求头（与 McpHarness.rpc 同口径）。"""
    return {
        "Host": "tradeck.example.com",
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "MCP-Protocol-Version": "2025-11-25",
        "Authorization": f"Bearer {token}",
    }


def _snapshot(status: str, **extra) -> dict:
    return {
        "task_id": TASK_ID,
        "status": status,
        "progress": {"day": 1, "total": 10, "date": "2025-01-02"},
        "created_at": 1.0,
        "started_at": 2.0,
        "finished_at": None,
        **extra,
    }


class ToolsTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.h = McpHarness()
        await self.h.__aenter__()
        q = self.h.quant
        q.set(
            "GET",
            "/api/strategies",
            200,
            [{"id": "ma_golden_cross", "name": "均线金叉", "source": "builtin"}],
        )
        q.set(
            "GET",
            "/api/strategies/errors",
            200,
            [{"file": "bad.py", "source": "custom", "error": "SyntaxError"}],
        )
        q.set("GET", "/api/strategies/guide", 200, {"content": "# 策略开发精简指南"})
        q.set("POST", "/api/backtest/run", 202, {"task_id": TASK_ID})

    async def asyncTearDown(self) -> None:
        await self.h.__aexit__(None, None, None)

    # ---- 身份与 scope ----

    async def test_identity_headers_from_token_only(self) -> None:
        data = await self.h.call_tool_json("list_strategies")
        self.assertEqual(data["strategies"][0]["id"], "ma_golden_cross")
        self.assertEqual(data["load_errors"][0]["file"], "bad.py")
        for req in self.h.quant.calls:
            self.assertEqual(req.headers["x-user-id"], "u1")
            self.assertEqual(req.headers["x-service-token"], SERVICE_TOKEN)
            self.assertEqual(req.headers["x-service-name"], "mcp")
        # 只读令牌属于 u2
        self.h.quant.calls.clear()
        await self.h.call_tool_json("list_strategies", token=TOKEN_READONLY)
        self.assertTrue(all(r.headers["x-user-id"] == "u2" for r in self.h.quant.calls))

    async def test_injected_user_argument_ignored(self) -> None:
        # 工具参数里塞 user_id / X-User-Id：SDK 忽略未声明参数，身份仍只来自令牌
        resp = await self.h.rpc(
            "tools/call",
            {
                "name": "list_strategies",
                "arguments": {"user_id": "u999", "X-User-Id": "u999"},
            },
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertTrue(self.h.quant.calls)
        self.assertTrue(all(r.headers["x-user-id"] == "u1" for r in self.h.quant.calls))

    async def test_concurrent_calls_keep_identity_isolated(self) -> None:
        # 不同令牌并发调用（quant 侧故意让出事件循环）：每个请求的 X-User-Id 都只属于自己的令牌，
        # 不会因 contextvar / 共享状态串号
        async def echo_user(request: httpx2.Request) -> httpx2.Response:
            await asyncio.sleep(0.01)
            return httpx2.Response(
                200, json=[{"id": "s", "owner": request.headers["x-user-id"]}]
            )

        self.h.quant.routes[("GET", "/api/strategies")] = echo_user
        tokens = {TOKEN_FULL: "u1", TOKEN_READONLY: "u2", TOKEN_BACKTEST: "u3"}
        order = list(tokens) * 4
        results = await asyncio.gather(
            *(self.h.call_tool_json("list_strategies", token=t) for t in order)
        )
        for token, data in zip(order, results):
            self.assertEqual(data["strategies"][0]["owner"], tokens[token])

    async def test_tool_schema_has_no_user_parameter(self) -> None:
        resp = await self.h.rpc("tools/list")
        self.assertEqual(resp.status_code, 200)
        tools = {t["name"]: t for t in resp.json()["result"]["tools"]}
        self.assertEqual(
            set(tools),
            {
                "get_strategy_guide",
                "list_strategies",
                "get_strategy_code",
                "validate_strategy",
                "save_strategy",
                "run_backtest",
                "get_backtest_result",
                "cancel_backtest",
            },
        )
        for t in tools.values():
            props = set(t["inputSchema"].get("properties", {}))
            self.assertFalse(props & {"user", "user_id", "owner"}, t["name"])
        for name in (
            "get_strategy_guide",
            "list_strategies",
            "get_strategy_code",
            "get_backtest_result",
        ):
            self.assertTrue(tools[name]["annotations"]["readOnlyHint"], name)
        self.assertFalse(tools["save_strategy"]["annotations"]["readOnlyHint"])

    async def test_readonly_token_cannot_save(self) -> None:
        is_error, text = await self.h.call_tool(
            "save_strategy", {"code": STRATEGY_CODE}, token=TOKEN_READONLY
        )
        self.assertTrue(is_error)
        self.assertIn("strategy:write", text)
        self.assertEqual(self.h.quant.calls, [])

    async def test_scope_matrix(self) -> None:
        # 只读令牌：validate（write）与 run_backtest（backtest）都拒
        for name, args in (
            ("validate_strategy", {"code": STRATEGY_CODE}),
            ("run_backtest", {"strategy_id": "ma_golden_cross", "start": "2024-01-01"}),
            ("get_backtest_result", {"task_id": TASK_ID}),
        ):
            is_error, text = await self.h.call_tool(name, args, token=TOKEN_READONLY)
            self.assertTrue(is_error, name)
            self.assertIn("权限", text)
        # backtest 令牌可读不可写
        is_error, _ = await self.h.call_tool("get_strategy_guide", token=TOKEN_BACKTEST)
        self.assertFalse(is_error)
        is_error, text = await self.h.call_tool(
            "save_strategy", {"code": STRATEGY_CODE}, token=TOKEN_BACKTEST
        )
        self.assertTrue(is_error)
        self.assertIn("strategy:write", text)

    # ---- 配额 ----

    async def test_rate_limit_per_token(self) -> None:
        for i in range(60):
            is_error, text = await self.h.call_tool("get_strategy_guide")
            self.assertFalse(is_error, f"第 {i + 1} 次：{text}")
        is_error, text = await self.h.call_tool("get_strategy_guide")
        self.assertTrue(is_error)
        self.assertIn("每分钟最多 60 次", text)
        self.assertIn("秒后重试", text)
        # 其他令牌不受影响
        is_error, _ = await self.h.call_tool("get_strategy_guide", token=TOKEN_READONLY)
        self.assertFalse(is_error)
        # 滑动窗口过后恢复（verifier 缓存也随之过期，重新校验）
        self.h.clock.advance(61)
        is_error, _ = await self.h.call_tool("get_strategy_guide")
        self.assertFalse(is_error)

    async def test_backtest_submit_quota_per_user(self) -> None:
        args = {
            "strategy_id": "ma_golden_cross",
            "start": "2024-01-01",
            "universe": "hs300",
        }
        # quant 拒绝的提交同样计数（按提交尝试计）
        self.h.quant.set(
            "POST", "/api/backtest/run", 429, {"detail": "回测任务队列已满"}
        )
        for _ in range(30):
            self.h.clock.advance(1)  # 同时避开每分钟 60 次的调用配额
            is_error, text = await self.h.call_tool("run_backtest", args)
            self.assertTrue(is_error)
            self.assertIn("队列已满", text)
        is_error, text = await self.h.call_tool("run_backtest", args)
        self.assertTrue(is_error)
        self.assertIn("每小时最多 30 次", text)
        self.assertEqual(
            len([c for c in self.h.quant.calls if c.url.path == "/api/backtest/run"]),
            30,
        )

    # ---- 入参校验 ----

    async def test_universe_all_rejected(self) -> None:
        for uni in ("all", "ALL"):
            is_error, text = await self.h.call_tool(
                "run_backtest",
                {
                    "strategy_id": "ma_golden_cross",
                    "start": "2024-01-01",
                    "universe": uni,
                },
            )
            self.assertTrue(is_error)
            self.assertIn("universe=all", text)
        self.assertEqual(self.h.quant.calls, [])

    async def test_backtest_argument_validation(self) -> None:
        cases = [
            ({"strategy_id": "1bad", "start": "2024-01-01"}, "strategy_id 非法"),
            (
                {"strategy_id": "ok", "start": "2024-01-01", "universe": "nasdaq"},
                "universe 非法",
            ),
            (
                {
                    "strategy_id": "ok",
                    "start": "2024-01-01",
                    "symbols": [f"S{i}" for i in range(501)],
                },
                "symbols 过多",
            ),
            ({"strategy_id": "ok", "start": "2024-02-01", "end": "2024-01-01"}, "早于"),
            (
                {"strategy_id": "ok", "start": "2024-01-01", "max_positions": 0},
                "max_positions",
            ),
        ]
        for args, expect in cases:
            is_error, text = await self.h.call_tool("run_backtest", args)
            self.assertTrue(is_error, args)
            self.assertIn(expect, text)
        self.assertEqual(self.h.quant.calls, [])

    async def test_run_backtest_payload(self) -> None:
        data = await self.h.call_tool_json(
            "run_backtest",
            {
                "strategy_id": "ma_golden_cross",
                "start": "2024-01-01",
                "end": "2024-06-30",
                "symbols": ["600519.SH", " AAPL "],
                "universe": "hs300",
                "params": {"fast": 5},
                "commission_pct": 0.0003,
            },
        )
        self.assertEqual(data["task_id"], TASK_ID)
        body = json.loads(self.h.quant.calls[-1].content)
        self.assertEqual(body["strategy_id"], "ma_golden_cross")
        self.assertEqual(body["start"], "2024-01-01")
        self.assertEqual(body["end"], "2024-06-30")
        self.assertEqual(body["symbols"], ["600519.SH", "AAPL"])
        self.assertNotIn("universe", body)  # symbols 显式优先
        self.assertEqual(body["params"], {"fast": 5})
        self.assertEqual(body["sim_mode"], "position")
        self.assertEqual(body["initial_capital"], 1_000_000)
        self.assertEqual(body["max_positions"], 10)
        self.assertEqual(body["commission_pct"], 0.0003)
        self.assertNotIn("stamp_tax_pct", body)
        self.assertNotIn("user", body)

    async def test_default_universe_sent_explicitly(self) -> None:
        # symbols / universe 都留空：显式下发 hs300（与工具说明、quant/web 默认一致，不依赖 quant 默认值）
        await self.h.call_tool_json(
            "run_backtest", {"strategy_id": "ma_golden_cross", "start": "2024-01-01"}
        )
        body = json.loads(self.h.quant.calls[-1].content)
        self.assertEqual(body["universe"], "hs300")
        self.assertNotIn("symbols", body)

    async def test_symbols_whitelist_blocks_path_traversal(self) -> None:
        # quant 用 symbol 直接拼缓存文件名：含 / 等字符的代码必须在 mcp 侧拦下，且不消耗回测配额
        for bad in ("X/../../../etc/pwned", "600519.SH;rm", "a" * 21, "600519 SH"):
            is_error, text = await self.h.call_tool(
                "run_backtest",
                {
                    "strategy_id": "ma_golden_cross",
                    "start": "2024-01-01",
                    "symbols": ["600519.SH", bad],
                },
            )
            self.assertTrue(is_error, bad)
            self.assertIn("symbols 含非法代码", text)
        self.assertEqual(self.h.quant.calls, [])

    async def test_symbols_normalized_upper_and_deduped(self) -> None:
        await self.h.call_tool_json(
            "run_backtest",
            {
                "strategy_id": "ma_golden_cross",
                "start": "2024-01-01",
                "symbols": ["600519.sh", "aapl", "600519.SH", " ", "BRK-B"],
            },
        )
        body = json.loads(self.h.quant.calls[-1].content)
        self.assertEqual(body["symbols"], ["600519.SH", "AAPL", "BRK-B"])

    async def test_symbols_limit_counts_after_dedup(self) -> None:
        # 去重后不超限即放行（重复代码不应把合法请求顶出上限）
        syms = [f"{600000 + i:06d}.SH" for i in range(500)] * 2
        await self.h.call_tool_json(
            "run_backtest",
            {"strategy_id": "ma_golden_cross", "start": "2024-01-01", "symbols": syms},
        )
        body = json.loads(self.h.quant.calls[-1].content)
        self.assertEqual(len(body["symbols"]), 500)

    async def test_non_finite_numbers_rejected_without_quota(self) -> None:
        # initial_capital 走 schema 校验；params 是自由结构，NaN/Infinity 须在本地拦下（JSON 无法编码）
        cases = [
            '{"strategy_id":"ok","start":"2024-01-01","initial_capital":"inf"}',
            '{"strategy_id":"ok","start":"2024-01-01","params":{"x":Infinity}}',
            '{"strategy_id":"ok","start":"2024-01-01","params":{"x":NaN}}',
        ]
        async with McpHarness(make_settings(backtests_per_hour=1)) as h:
            h.quant.set("POST", "/api/backtest/run", 202, {"task_id": TASK_ID})
            for args in cases:
                raw = (
                    '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":'
                    '{"name":"run_backtest","arguments":' + args + "}}"
                )
                resp = await h.http.post(
                    "/mcp", headers=_rpc_headers(TOKEN_FULL), content=raw
                )
                self.assertEqual(resp.status_code, 200, resp.text)
                result = resp.json()["result"]
                self.assertTrue(result["isError"], args)
                text = result["content"][0]["text"]
                # 不是 SDK 的通用崩溃文案（"Error executing tool run_backtest" 后无说明）
                self.assertNotEqual(text.strip(), "Error executing tool run_backtest")
            self.assertEqual(h.quant.calls, [])
            # 本地拒绝不计回测配额：上限 1 次时仍能正常提交
            data = await h.call_tool_json(
                "run_backtest", {"strategy_id": "ok", "start": "2024-01-01"}
            )
            self.assertEqual(data["task_id"], TASK_ID)

    async def test_code_size_limit(self) -> None:
        async with McpHarness(make_settings(max_code_bytes=100)) as h:
            is_error, text = await h.call_tool(
                "validate_strategy", {"code": "#" + "中" * 40}
            )
            self.assertTrue(is_error)
            self.assertIn("上限 100 字节", text)
            self.assertEqual(h.quant.calls, [])

    async def test_task_id_format(self) -> None:
        for bad in ("../etc", TASK_ID.upper(), TASK_ID[:-1]):
            is_error, text = await self.h.call_tool(
                "get_backtest_result", {"task_id": bad}
            )
            self.assertTrue(is_error)
            self.assertIn("task_id 非法", text)
        is_error, _ = await self.h.call_tool(
            "get_backtest_result", {"task_id": TASK_ID, "limit": 201}
        )
        self.assertTrue(is_error)
        is_error, _ = await self.h.call_tool(
            "get_backtest_result", {"task_id": TASK_ID, "wait_seconds": 51}
        )
        self.assertTrue(is_error)
        is_error, _ = await self.h.call_tool(
            "get_backtest_result", {"task_id": TASK_ID, "section": "raw"}
        )
        self.assertTrue(is_error)
        self.assertEqual(self.h.quant.calls, [])

    # ---- quant 错误翻译 ----

    async def test_quant_4xx_detail_passthrough_truncated(self) -> None:
        self.h.quant.set(
            "POST", "/api/strategies/save", 409, {"detail": "内置策略只读" + "x" * 5000}
        )
        is_error, text = await self.h.call_tool(
            "save_strategy", {"code": STRATEGY_CODE, "overwrite_id": "ma_golden_cross"}
        )
        self.assertTrue(is_error)
        self.assertIn("HTTP 409", text)
        self.assertIn("内置策略只读", text)
        self.assertIn("已截断", text)
        self.assertLess(len(text), 2300)
        body = json.loads(self.h.quant.calls[-1].content)
        self.assertEqual(body["overwrite_id"], "ma_golden_cross")

    async def test_quant_422_list_detail(self) -> None:
        self.h.quant.set(
            "POST",
            "/api/strategies/save",
            422,
            {
                "detail": [
                    {
                        "loc": ["body", "code"],
                        "msg": "String should have at least 20 characters",
                    }
                ]
            },
        )
        is_error, text = await self.h.call_tool(
            "save_strategy", {"code": STRATEGY_CODE}
        )
        self.assertTrue(is_error)
        self.assertIn("code: String should have at least 20 characters", text)

    async def test_quant_5xx_and_network_generic(self) -> None:
        self.h.quant.set(
            "GET", "/api/strategies/guide", 500, {"detail": "内部堆栈 /app/secret.py"}
        )
        is_error, text = await self.h.call_tool("get_strategy_guide")
        self.assertTrue(is_error)
        self.assertIn(UNAVAILABLE_MESSAGE, text)
        self.assertNotIn("secret", text)

        def boom(request: httpx2.Request) -> httpx2.Response:
            raise httpx2.ConnectError("refused", request=request)

        self.h.quant.routes[("GET", "/api/strategies/guide")] = boom
        is_error, text = await self.h.call_tool("get_strategy_guide")
        self.assertTrue(is_error)
        self.assertIn(UNAVAILABLE_MESSAGE, text)

    async def test_quant_rejects_service_token_is_generic(self) -> None:
        # quant 401/403 = mcp 服务令牌配置错误：不把内部鉴权细节透给 agent，只给通用文案并告警
        for status in (401, 403):
            self.h.quant.set(
                "GET",
                "/api/strategies/guide",
                status,
                {
                    "detail": "缺少有效的 X-Service-Token（quant 仅接受 web / mcp 服务调用）"
                },
            )
            with self.assertLogs("app.quant_client", level="WARNING"):
                is_error, text = await self.h.call_tool("get_strategy_guide")
            self.assertTrue(is_error, status)
            self.assertIn(UNAVAILABLE_MESSAGE, text)
            self.assertNotIn("X-Service-Token", text)

    async def test_quant_4xx_without_detail(self) -> None:
        # detail 缺失/为 null：回落 HTTP 状态码，而不是把 "null" 回显给 agent
        self.h.quant.set("POST", "/api/strategies/save", 409, {"detail": None})
        is_error, text = await self.h.call_tool(
            "save_strategy", {"code": STRATEGY_CODE}
        )
        self.assertTrue(is_error)
        self.assertIn("HTTP 409", text)
        self.assertNotIn("null", text)

    async def test_quant_timeout_message_distinct(self) -> None:
        # 超时时服务端可能仍在处理：文案须提示「先确认再重试」，与「不可用」区分
        def slow(request: httpx2.Request) -> httpx2.Response:
            raise httpx2.ReadTimeout("slow", request=request)

        self.h.quant.routes[("POST", "/api/strategies/save")] = slow
        with self.assertLogs("app.quant_client", level="WARNING"):
            is_error, text = await self.h.call_tool(
                "save_strategy", {"code": STRATEGY_CODE}
            )
        self.assertTrue(is_error)
        self.assertIn(TIMEOUT_MESSAGE, text)
        self.assertNotIn(UNAVAILABLE_MESSAGE, text)

    async def test_request_timeouts_fit_gateway_budget(self) -> None:
        # 每个 quant 请求都带显式超时；默认超时须长于 quant 沙箱试加载上限 60s（否则「试加载超时」
        # 的业务结果被本端超时吞掉），且 PAT 校验 + 请求、长轮询 + 单次轮询都须 ≤ nginx 90s
        nginx_read_timeout = 90.0
        sandbox_trial_timeout = 60.0
        self.h.quant.set("POST", "/api/strategies/validate", 200, {"valid": True})
        self.h.quant.set(
            "GET", f"/api/backtest/task/{TASK_ID}", 200, _snapshot("running")
        )
        await self.h.call_tool_json("validate_strategy", {"code": STRATEGY_CODE})
        validate_req = self.h.quant.calls[-1]
        await self.h.call_tool_json("get_backtest_result", {"task_id": TASK_ID})
        poll_req = self.h.quant.calls[-1]

        self.assertEqual(validate_req.extensions["timeout"]["read"], QUANT_TIMEOUT.read)
        self.assertEqual(poll_req.extensions["timeout"]["read"], TASK_TIMEOUT.read)
        self.assertGreater(QUANT_TIMEOUT.read, sandbox_trial_timeout)
        self.assertLessEqual(AUTH_TIMEOUT.read + QUANT_TIMEOUT.read, nginx_read_timeout)
        self.assertLessEqual(
            AUTH_TIMEOUT.read
            + MAX_WAIT_SECONDS
            + POLL_INTERVAL_SECONDS
            + TASK_TIMEOUT.read,
            nginx_read_timeout,
        )

    async def test_errors_endpoint_404_is_empty(self) -> None:
        del self.h.quant.routes[("GET", "/api/strategies/errors")]
        data = await self.h.call_tool_json("list_strategies")
        self.assertEqual(data["load_errors"], [])
        self.assertNotIn("load_errors_unavailable", data)

    async def test_validate_passthrough(self) -> None:
        self.h.quant.set(
            "POST",
            "/api/strategies/validate",
            200,
            {"valid": False, "error": "禁止 import os", "meta": {}},
        )
        data = await self.h.call_tool_json("validate_strategy", {"code": STRATEGY_CODE})
        self.assertEqual(data, {"valid": False, "error": "禁止 import os", "meta": {}})
        self.assertEqual(
            json.loads(self.h.quant.calls[-1].content), {"code": STRATEGY_CODE}
        )

    async def test_get_strategy_code(self) -> None:
        self.h.quant.set(
            "GET",
            "/api/strategies/ma_golden_cross/code",
            200,
            {
                "id": "ma_golden_cross",
                "name": "均线金叉",
                "source": "builtin",
                "code": "META = {}",
            },
        )
        data = await self.h.call_tool_json(
            "get_strategy_code", {"strategy_id": "ma_golden_cross"}
        )
        self.assertEqual(data["code"], "META = {}")
        is_error, _ = await self.h.call_tool(
            "get_strategy_code", {"strategy_id": "../../etc/passwd"}
        )
        self.assertTrue(is_error)

    # ---- 任务结果 ----

    async def test_task_404_message(self) -> None:
        self.h.quant.set(
            "GET", f"/api/backtest/task/{TASK_ID}", 404, {"detail": "回测任务不存在"}
        )
        self.h.quant.set(
            "POST",
            f"/api/backtest/task/{TASK_ID}/cancel",
            404,
            {"detail": "回测任务不存在"},
        )
        for name in ("get_backtest_result", "cancel_backtest"):
            is_error, text = await self.h.call_tool(name, {"task_id": TASK_ID})
            self.assertTrue(is_error, name)
            self.assertIn(TASK_NOT_FOUND_MESSAGE, text)

    async def test_long_poll_until_done(self) -> None:
        polls = {"n": 0}
        result = big_position_result(n_days=300, n_trades=120, n_symbols=40)

        def task(request: httpx2.Request) -> httpx2.Response:
            polls["n"] += 1
            if polls["n"] < 4:
                return httpx2.Response(200, json=_snapshot("running"))
            return httpx2.Response(
                200, json=_snapshot("done", finished_at=9.0, result=result)
            )

        self.h.quant.routes[("GET", f"/api/backtest/task/{TASK_ID}")] = task
        start = self.h.clock.now
        data = await self.h.call_tool_json(
            "get_backtest_result", {"task_id": TASK_ID, "wait_seconds": 30}
        )
        self.assertEqual(data["status"], "done")
        self.assertEqual(polls["n"], 4)
        self.assertAlmostEqual(self.h.clock.now - start, 6.0)  # 每 2 秒一次
        self.assertEqual(data["summary"]["trade_count"], 120)
        self.assertNotIn("result", data)

    async def test_long_poll_timeout_returns_running(self) -> None:
        self.h.quant.set(
            "GET", f"/api/backtest/task/{TASK_ID}", 200, _snapshot("running")
        )
        start = self.h.clock.now
        data = await self.h.call_tool_json(
            "get_backtest_result", {"task_id": TASK_ID, "wait_seconds": 5}
        )
        self.assertEqual(data["status"], "running")
        self.assertIn("hint", data)
        self.assertAlmostEqual(self.h.clock.now - start, 5.0)
        # wait_seconds=0 只查一次
        n = len(self.h.quant.calls)
        await self.h.call_tool_json("get_backtest_result", {"task_id": TASK_ID})
        self.assertEqual(len(self.h.quant.calls), n + 1)

    async def test_failed_task_error_truncated(self) -> None:
        self.h.quant.set(
            "GET",
            f"/api/backtest/task/{TASK_ID}",
            200,
            _snapshot("failed", error="策略执行失败" + "e" * 5000),
        )
        data = await self.h.call_tool_json("get_backtest_result", {"task_id": TASK_ID})
        self.assertEqual(data["status"], "failed")
        self.assertIn("已截断", data["error"])
        self.assertNotIn("summary", data)

    async def test_summary_tool_output_under_10kb(self) -> None:
        result = big_position_result()
        self.h.quant.set(
            "GET",
            f"/api/backtest/task/{TASK_ID}",
            200,
            _snapshot("done", finished_at=9.0, result=result),
        )
        is_error, text = await self.h.call_tool(
            "get_backtest_result", {"task_id": TASK_ID}
        )
        self.assertFalse(is_error)
        self.assertLessEqual(len(text.encode("utf-8")), 10 * 1024)
        data = json.loads(text)
        self.assertEqual(data["summary"]["trade_count"], 8000)
        self.assertLessEqual(len(data["summary"]["equity_curve"]), 50)

    async def test_section_pagination(self) -> None:
        result = big_position_result(n_days=400, n_trades=250, n_symbols=60)
        self.h.quant.set(
            "GET",
            f"/api/backtest/task/{TASK_ID}",
            200,
            _snapshot("done", finished_at=9.0, result=result),
        )
        page = await self.h.call_tool_json(
            "get_backtest_result",
            {"task_id": TASK_ID, "section": "trades", "offset": 200, "limit": 100},
        )
        self.assertEqual(
            (page["total"], page["offset"], page["limit"]), (250, 200, 100)
        )
        self.assertEqual(len(page["items"]), 50)
        self.assertEqual(page["items"][0], result["trades"][200])
        page = await self.h.call_tool_json(
            "get_backtest_result",
            {"task_id": TASK_ID, "section": "per_symbol", "limit": 10},
        )
        self.assertEqual(page["total"], 60)
        self.assertEqual(page["items"], result["per_symbol_stats"][:10])
        page = await self.h.call_tool_json(
            "get_backtest_result",
            {"task_id": TASK_ID, "section": "equity", "offset": 390},
        )
        self.assertEqual(page["total"], 400)
        self.assertEqual(len(page["items"]), 10)

    async def test_cancel(self) -> None:
        self.h.quant.set(
            "POST",
            f"/api/backtest/task/{TASK_ID}/cancel",
            200,
            _snapshot("cancelled", finished_at=3.0),
        )
        data = await self.h.call_tool_json("cancel_backtest", {"task_id": TASK_ID})
        self.assertEqual(data["status"], "cancelled")
        self.assertEqual(self.h.quant.calls[-1].headers["x-user-id"], "u1")


class InstructionsTest(unittest.IsolatedAsyncioTestCase):
    async def test_initialize_returns_instructions(self) -> None:
        async with McpHarness() as h:
            resp = await h.rpc(
                "initialize",
                {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "0"},
                },
            )
            self.assertEqual(resp.status_code, 200)
            instructions = resp.json()["result"]["instructions"]
            for keyword in (
                "get_strategy_guide",
                "polars",
                "numpy",
                "datetime",
                "from app.strategy.base",
                "from app.matrix",
                "validate_strategy",
                "save_strategy",
                "get_backtest_result",
            ):
                self.assertIn(keyword, instructions)
            self.assertEqual(h.api.calls[-1].headers["x-service-token"], SERVICE_TOKEN)


if __name__ == "__main__":
    unittest.main()
