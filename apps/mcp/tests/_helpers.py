"""mcp 单测共用夹具：假时钟、api / quant 的 MockTransport、经 ASGI 调 /mcp 的 JSON-RPC 客户端。

不起真实网络与 uvicorn：httpx2.ASGITransport 直接驱动 create_app() 的 Starlette 应用；
ASGITransport 不跑 lifespan，故由 McpHarness 在后台 task 里进入 app.router.lifespan_context
（等价于 uvicorn 启动时进入 session_manager.run()）。
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Callable
from typing import Any

import httpx2

from app.config import Settings
from app.main import create_app

PUBLIC_URL = "https://tradeck.example.com"
PUBLIC_HOST = "tradeck.example.com"
SERVICE_TOKEN = "svc-mcp-secret"

TOKEN_FULL = "tdk_pat_full_access_token_000000000000000000000"
TOKEN_READONLY = "tdk_pat_read_only_token_00000000000000000000000"
TOKEN_BACKTEST = "tdk_pat_backtest_only_token_0000000000000000000"
ALL_SCOPES = ["strategy:read", "strategy:write", "backtest"]


def make_settings(**overrides: Any) -> Settings:
    base = dict(
        service_token=SERVICE_TOKEN,
        auth_api_url="http://api:8080",
        quant_api_url="http://quant:8083",
        public_url=PUBLIC_URL,
        rate_per_minute=60,
        backtests_per_hour=30,
        max_code_bytes=200_000,
    )
    base.update(overrides)
    return Settings(**base)


class FakeClock:
    """可手动推进的单调时钟（verifier 缓存 / 配额窗口 / 长轮询共用）。"""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds

    async def sleep(self, seconds: float) -> None:
        self.advance(seconds)


class FakeAuthApi:
    """模拟 api 的 POST /api/auth/tokens/verify。"""

    def __init__(self) -> None:
        self.tokens: dict[str, dict] = {
            TOKEN_FULL: {"user_id": "u1", "scopes": ALL_SCOPES},
            TOKEN_READONLY: {"user_id": "u2", "scopes": ["strategy:read"]},
            TOKEN_BACKTEST: {"user_id": "u3", "scopes": ["strategy:read", "backtest"]},
        }
        self.calls: list[httpx2.Request] = []
        self.fail_network = False
        self.status_override: int | None = None

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        self.calls.append(request)
        if self.fail_network:
            raise httpx2.ConnectError("api down", request=request)
        if request.url.path != "/api/auth/tokens/verify" or request.method != "POST":
            return httpx2.Response(404, json={"detail": "not found"})
        if request.headers.get("x-service-token") != SERVICE_TOKEN:
            return httpx2.Response(403, json={"detail": "service token"})
        if self.status_override is not None:
            return httpx2.Response(self.status_override, json={"detail": "override"})
        token = json.loads(request.content).get("token")
        info = self.tokens.get(token)
        if info is None:
            return httpx2.Response(401, json={"detail": "无效令牌"})
        return httpx2.Response(
            200,
            json={
                **info,
                "expires_at": "2099-01-01T00:00:00+00:00",
                "token_id": 7,
            },
        )

    @property
    def transport(self) -> httpx2.MockTransport:
        return httpx2.MockTransport(self.handler)


class FakeQuant:
    """模拟 quant 端点；routes 键为 (method, path)，值为返回 Response 的函数或固定 (status, body)。"""

    def __init__(self) -> None:
        self.calls: list[httpx2.Request] = []
        self.routes: dict[
            tuple[str, str],
            Callable[[httpx2.Request], httpx2.Response] | tuple[int, Any],
        ] = {}

    def set(self, method: str, path: str, status: int, body: Any) -> None:
        self.routes[(method, path)] = (status, body)

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        self.calls.append(request)
        route = self.routes.get((request.method, request.url.path))
        if route is None:
            return httpx2.Response(
                404, json={"detail": f"no route {request.method} {request.url.path}"}
            )
        if callable(route):
            return route(request)
        status, body = route
        return httpx2.Response(status, json=body)

    @property
    def transport(self) -> httpx2.MockTransport:
        return httpx2.MockTransport(self.handler)


class McpHarness:
    """异步上下文：进入应用 lifespan，提供 HTTP 客户端与 JSON-RPC 工具调用。"""

    def __init__(self, settings: Settings | None = None) -> None:
        self.clock = FakeClock()
        self.api = FakeAuthApi()
        self.quant = FakeQuant()
        self.app = create_app(
            settings or make_settings(),
            auth_transport=self.api.transport,
            quant_transport=self.quant.transport,
            clock=self.clock,
            sleep=self.clock.sleep,
        )
        self.http: httpx2.AsyncClient | None = None
        self._stop: asyncio.Event | None = None
        self._lifespan_task: asyncio.Task | None = None

    async def __aenter__(self) -> McpHarness:
        # lifespan 必须在同一个 task 内进入与退出（anyio task group 约束），而
        # IsolatedAsyncioTestCase 的 setUp / tearDown 分属不同 task——放进专属后台 task 托管
        ready = asyncio.Event()
        self._stop = asyncio.Event()

        async def hold_lifespan() -> None:
            async with self.app.router.lifespan_context(self.app):
                ready.set()
                await self._stop.wait()

        self._lifespan_task = asyncio.create_task(hold_lifespan())
        waiter = asyncio.create_task(ready.wait())
        await asyncio.wait(
            {waiter, self._lifespan_task}, return_when=asyncio.FIRST_COMPLETED
        )
        if not ready.is_set():
            waiter.cancel()
            await self._lifespan_task  # 启动失败：抛出原始异常
        self.http = httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=self.app),
            base_url=PUBLIC_URL,
        )
        return self

    async def __aexit__(self, *exc: Any) -> None:
        assert self.http is not None
        await self.http.aclose()
        self._stop.set()
        await self._lifespan_task

    async def rpc(
        self,
        method: str,
        params: dict | None = None,
        token: str | None = TOKEN_FULL,
        host: str = PUBLIC_HOST,
    ) -> httpx2.Response:
        assert self.http is not None
        headers = {
            "Host": host,
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "MCP-Protocol-Version": "2025-11-25",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        body = {
            "jsonrpc": "2.0",
            "id": uuid.uuid4().hex[:8],
            "method": method,
            "params": params or {},
        }
        return await self.http.post("/mcp", headers=headers, content=json.dumps(body))

    async def call_tool(
        self, name: str, arguments: dict | None = None, token: str | None = TOKEN_FULL
    ) -> tuple[bool, str]:
        """调工具，返回 (is_error, 文本内容)；HTTP 非 200 或 JSON-RPC 协议错误直接断言失败。"""
        resp = await self.rpc(
            "tools/call", {"name": name, "arguments": arguments or {}}, token=token
        )
        assert resp.status_code == 200, f"HTTP {resp.status_code}: {resp.text}"
        data = resp.json()
        assert "result" in data, f"JSON-RPC 错误：{data}"
        result = data["result"]
        text = "".join(
            c.get("text", "")
            for c in result.get("content", [])
            if c.get("type") == "text"
        )
        return bool(result.get("isError")), text

    async def call_tool_json(
        self, name: str, arguments: dict | None = None, token: str | None = TOKEN_FULL
    ) -> dict:
        is_error, text = await self.call_tool(name, arguments, token)
        assert not is_error, f"工具返回错误：{text}"
        return json.loads(text)
