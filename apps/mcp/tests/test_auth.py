"""PatVerifier 单测：前缀拦截、verify 请求契约、成功/失败缓存时长、各类失败降级为 None。"""

from __future__ import annotations

import json
import unittest

import httpx2

from app.auth import FAILURE_TTL_SECONDS, SUCCESS_TTL_SECONDS, PatVerifier
from tests._helpers import (
    ALL_SCOPES,
    PUBLIC_URL,
    SERVICE_TOKEN,
    TOKEN_FULL,
    FakeAuthApi,
    FakeClock,
    make_settings,
)


class PatVerifierTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.api = FakeAuthApi()
        self.clock = FakeClock()
        self.http = httpx2.AsyncClient(
            base_url="http://api:8080", transport=self.api.transport
        )
        self.verifier = PatVerifier(make_settings(), self.http, clock=self.clock)

    async def asyncTearDown(self) -> None:
        await self.http.aclose()

    async def test_non_pat_prefix_rejected_without_remote_call(self) -> None:
        for bad in (
            "",
            "abc",
            "tdk_session_xxx",
            "Bearer tdk_pat_x",
            "tdk_pat_" + "x" * 300,
        ):
            self.assertIsNone(await self.verifier.verify_token(bad))
        self.assertEqual(self.api.calls, [])

    async def test_success_maps_to_access_token(self) -> None:
        tok = await self.verifier.verify_token(TOKEN_FULL)
        self.assertIsNotNone(tok)
        assert tok is not None
        self.assertEqual(tok.client_id, "u1")
        self.assertEqual(tok.subject, "u1")
        self.assertEqual(tok.scopes, ALL_SCOPES)
        self.assertEqual(tok.resource, PUBLIC_URL + "/mcp")
        self.assertEqual(tok.expires_at, 4070908800)  # 2099-01-01T00:00:00Z
        self.assertEqual(tok.token, TOKEN_FULL)

    async def test_verify_request_contract(self) -> None:
        await self.verifier.verify_token(TOKEN_FULL)
        self.assertEqual(len(self.api.calls), 1)
        req = self.api.calls[0]
        self.assertEqual(req.method, "POST")
        self.assertEqual(req.url.path, "/api/auth/tokens/verify")
        self.assertEqual(req.headers["x-service-token"], SERVICE_TOKEN)
        self.assertEqual(req.headers["x-service-name"], "mcp")
        self.assertEqual(json.loads(req.content), {"token": TOKEN_FULL})

    async def test_success_cached_30s(self) -> None:
        await self.verifier.verify_token(TOKEN_FULL)
        self.clock.advance(SUCCESS_TTL_SECONDS - 1)
        self.assertIsNotNone(await self.verifier.verify_token(TOKEN_FULL))
        self.assertEqual(len(self.api.calls), 1)
        # 过期后重新校验：期间被撤销则立即生效
        del self.api.tokens[TOKEN_FULL]
        self.clock.advance(2)
        self.assertIsNone(await self.verifier.verify_token(TOKEN_FULL))
        self.assertEqual(len(self.api.calls), 2)

    async def test_failure_cached_5s(self) -> None:
        bad = "tdk_pat_unknown_token"
        self.assertIsNone(await self.verifier.verify_token(bad))
        self.assertIsNone(await self.verifier.verify_token(bad))
        self.assertEqual(len(self.api.calls), 1)
        self.clock.advance(FAILURE_TTL_SECONDS + 0.1)
        self.assertIsNone(await self.verifier.verify_token(bad))
        self.assertEqual(len(self.api.calls), 2)

    async def test_network_error_returns_none(self) -> None:
        self.api.fail_network = True
        with self.assertLogs("app.auth", level="WARNING"):
            self.assertIsNone(await self.verifier.verify_token(TOKEN_FULL))
        # 失败只缓存 5 秒：api 恢复后很快即可通过
        self.api.fail_network = False
        self.clock.advance(FAILURE_TTL_SECONDS + 0.1)
        self.assertIsNotNone(await self.verifier.verify_token(TOKEN_FULL))

    async def test_non_200_returns_none(self) -> None:
        for status in (401, 403, 500, 502):
            self.api.status_override = status
            self.clock.advance(FAILURE_TTL_SECONDS + 0.1)
            self.assertIsNone(await self.verifier.verify_token(TOKEN_FULL), status)

    async def test_malformed_body_returns_none(self) -> None:
        bodies = [
            ["not", "object"],
            {"user_id": "u1; drop", "scopes": ["backtest"], "expires_at": None},
            {"user_id": "u1", "scopes": "backtest", "expires_at": None},
            {"user_id": "u1", "scopes": ["backtest"], "expires_at": "not-a-date"},
        ]
        for body in bodies:
            transport = httpx2.MockTransport(
                lambda req, b=body: httpx2.Response(200, json=b)
            )
            async with httpx2.AsyncClient(
                base_url="http://api:8080", transport=transport
            ) as http:
                verifier = PatVerifier(make_settings(), http, clock=self.clock)
                self.assertIsNone(await verifier.verify_token(TOKEN_FULL), body)


if __name__ == "__main__":
    unittest.main()
