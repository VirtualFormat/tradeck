"""HTTP 层单测：/health 不鉴权、/mcp 无/错 Bearer 401 + WWW-Authenticate、resource metadata 可访问、
公网 Host 不 421 而陌生 Host 421。全部经 httpx2.ASGITransport 直驱 ASGI 应用。
"""

from __future__ import annotations

import unittest

from tests._helpers import (
    PUBLIC_HOST,
    PUBLIC_URL,
    TOKEN_FULL,
    McpHarness,
    make_settings,
)


class HttpLayerTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.h = McpHarness()
        await self.h.__aenter__()

    async def asyncTearDown(self) -> None:
        await self.h.__aexit__(None, None, None)

    async def test_health_ok_without_auth(self) -> None:
        for host in (PUBLIC_HOST, "127.0.0.1:8084", "mcp:8084"):
            resp = await self.h.http.get("/health", headers={"Host": host})
            self.assertEqual(resp.status_code, 200, host)
            self.assertEqual(resp.json(), {"status": "ok"})
        self.assertEqual(self.h.api.calls, [])

    async def test_mcp_without_bearer_401(self) -> None:
        resp = await self.h.rpc("tools/list", token=None)
        self.assertEqual(resp.status_code, 401)
        www = resp.headers["www-authenticate"]
        self.assertTrue(www.startswith("Bearer "))
        self.assertIn(
            f'resource_metadata="{PUBLIC_URL}/.well-known/oauth-protected-resource/mcp"',
            www,
        )
        self.assertEqual(resp.json()["error"], "invalid_token")
        self.assertEqual(self.h.api.calls, [])

    async def test_mcp_with_bad_bearer_401(self) -> None:
        for token in ("not-a-pat", "tdk_pat_revoked_or_unknown"):
            resp = await self.h.rpc("tools/list", token=token)
            self.assertEqual(resp.status_code, 401, token)
            self.assertIn("resource_metadata=", resp.headers["www-authenticate"])
        # 只有 tdk_pat_ 前缀的才打 api
        self.assertEqual(len(self.h.api.calls), 1)

    async def test_api_down_is_401_not_500(self) -> None:
        self.h.api.fail_network = True
        resp = await self.h.rpc("tools/list")
        self.assertEqual(resp.status_code, 401)

    async def test_resource_metadata_public(self) -> None:
        resp = await self.h.http.get(
            "/.well-known/oauth-protected-resource/mcp", headers={"Host": PUBLIC_HOST}
        )
        self.assertEqual(resp.status_code, 200)
        meta = resp.json()
        self.assertEqual(meta["resource"], PUBLIC_URL + "/mcp")
        self.assertEqual(meta["authorization_servers"], [PUBLIC_URL])
        self.assertIn("header", meta.get("bearer_methods_supported", ["header"]))

    async def test_public_host_not_421(self) -> None:
        resp = await self.h.rpc("tools/list", token=TOKEN_FULL, host=PUBLIC_HOST)
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertIn("tools", resp.json()["result"])

    async def test_unknown_host_421(self) -> None:
        resp = await self.h.rpc("tools/list", token=TOKEN_FULL, host="evil.example.org")
        self.assertEqual(resp.status_code, 421)

    async def test_extra_allowed_hosts(self) -> None:
        async with McpHarness(make_settings(extra_allowed_hosts=("mcp:8084",))) as h:
            resp = await h.rpc("tools/list", token=TOKEN_FULL, host="mcp:8084")
            self.assertEqual(resp.status_code, 200, resp.text)

    async def test_protocol_version_modern_path_also_authenticated(self) -> None:
        # 新版协议（无 initialize 握手）走 SDK 另一条处理路径，鉴权同样在 HTTP 层生效
        headers = {
            "Host": PUBLIC_HOST,
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "MCP-Protocol-Version": "2026-07-28",
        }
        resp = await self.h.http.post(
            "/mcp",
            headers=headers,
            content='{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}',
        )
        self.assertEqual(resp.status_code, 401)


class SettingsTest(unittest.TestCase):
    def test_allowed_hosts_derived_from_public_url(self) -> None:
        s = make_settings(
            public_url="https://tradeck.virtualformat.cn/",
            extra_allowed_hosts=("a:1", ""),
        )
        self.assertEqual(s.resource_url, "https://tradeck.virtualformat.cn/mcp")
        self.assertEqual(
            s.allowed_hosts,
            ["tradeck.virtualformat.cn", "tradeck.virtualformat.cn:*", "a:1"],
        )
        self.assertEqual(s.allowed_origins, ["https://tradeck.virtualformat.cn"])

    def test_load_settings_env(self) -> None:
        import os
        from unittest import mock

        from app.config import load_settings

        env = {
            "MCP_SERVICE_TOKEN": "t",
            "MCP_PUBLIC_URL": "https://x.example.com",
            "MCP_ALLOWED_HOSTS": "mcp:8084, 127.0.0.1:8084",
            "MCP_RATE_PER_MINUTE": "abc",
            "MCP_BACKTESTS_PER_HOUR": "5",
            "AUTH_API_URL": "http://api:8080/",
        }
        with mock.patch.dict(os.environ, env, clear=False), self.assertLogs(
            "app.config", level="WARNING"
        ):
            s = load_settings()
        self.assertEqual(s.rate_per_minute, 60)
        self.assertEqual(s.backtests_per_hour, 5)
        self.assertEqual(s.auth_api_url, "http://api:8080")
        self.assertEqual(s.quant_api_url, "http://quant:8083")
        self.assertIn("mcp:8084", s.allowed_hosts)
        self.assertIn("127.0.0.1:8084", s.allowed_hosts)


if __name__ == "__main__":
    unittest.main()
