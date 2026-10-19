"""quant 入站鉴权（P0 MCP 加固）单测。

覆盖点：
- 中间件：未配置 INBOUND_SERVICE_TOKENS 放行；配置后无/错令牌 401、正确令牌放行、
  /health 不鉴权；非法 JSON 配置按未启用处理。
- current_user_id：未启用时缺省回落 default；启用后缺 X-User-Id 400；非法 id 400。
- migrate_default_user_namespace：整目录迁移、目标已存在跳过、幂等。

说明：TestClient 对本仓库 starlette 版本有挂起问题（见 test_ai_save），中间件用
最小 ASGI 调用直测（不起事件循环外的线程），端点依赖直接调函数。
"""
from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_TOKENS = json.dumps({"tok-web": "web-bff", "tok-mcp": "mcp"})


async def _call(app, path: str, headers: dict[str, str] | None = None) -> tuple[int, dict]:
    """最小 ASGI 调用：返回 (status, json body)。"""
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
        "client": ("127.0.0.1", 1234),
        "server": ("testserver", 80),
    }
    messages: list[dict] = []

    async def receive() -> dict:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict) -> None:
        messages.append(message)

    await app(scope, receive, send)
    status = next(m["status"] for m in messages if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body")
    return status, json.loads(body or b"null")


class _Downstream:
    """记录是否被调用的下游 ASGI app（返回 200 + 透出 consumer）。"""

    def __init__(self) -> None:
        self.called = False

    async def __call__(self, scope, receive, send) -> None:
        from starlette.responses import JSONResponse

        self.called = True
        consumer = (scope.get("state") or {}).get("service_consumer")
        await JSONResponse({"ok": True, "consumer": consumer})(scope, receive, send)


class InboundAuthMiddlewareTest(unittest.TestCase):
    def _run(self, tokens: str, path: str, headers: dict[str, str] | None = None):
        from app.inbound_auth import InboundAuthMiddleware

        downstream = _Downstream()
        with mock.patch("app.config.settings.INBOUND_SERVICE_TOKENS", tokens):
            status, body = asyncio.run(_call(InboundAuthMiddleware(downstream), path, headers))
        return status, body, downstream.called

    def test_disabled_passes_through(self) -> None:
        status, body, called = self._run("", "/api/strategies")
        self.assertEqual(status, 200)
        self.assertTrue(called)
        self.assertIsNone(body["consumer"])

    def test_missing_token_401(self) -> None:
        status, body, called = self._run(_TOKENS, "/api/strategies")
        self.assertEqual(status, 401)
        self.assertFalse(called)
        self.assertIn("X-Service-Token", body["detail"])

    def test_wrong_token_401(self) -> None:
        status, _, called = self._run(_TOKENS, "/api/strategies", {"X-Service-Token": "nope"})
        self.assertEqual(status, 401)
        self.assertFalse(called)

    def test_valid_token_passes_with_consumer(self) -> None:
        status, body, called = self._run(_TOKENS, "/api/strategies", {"X-Service-Token": "tok-mcp"})
        self.assertEqual(status, 200)
        self.assertTrue(called)
        self.assertEqual(body["consumer"], "mcp")

    def test_health_is_public(self) -> None:
        status, _, called = self._run(_TOKENS, "/health")
        self.assertEqual(status, 200)
        self.assertTrue(called)

    def test_invalid_config_fails_closed(self) -> None:
        """非空但非法的配置拒绝服务（503），绝不静默放行；/health 仍可探活。"""
        for bad in ("not-json", "[1,2]", '"str"', '{tok: "web-bff"}', '{"": "web-bff"}', "{}"):
            with self.subTest(config=bad):
                status, _, called = self._run(bad, "/api/strategies", {"X-Service-Token": "tok-web"})
                self.assertEqual(status, 503)
                self.assertFalse(called)
        status, _, called = self._run("not-json", "/health")
        self.assertEqual(status, 200)
        self.assertTrue(called)

    def test_invalid_config_still_requires_user_header(self) -> None:
        from fastapi import HTTPException

        from app.api import current_user_id

        with mock.patch("app.config.settings.INBOUND_SERVICE_TOKENS", "not-json"):
            with self.assertRaises(HTTPException):
                current_user_id(None)

    def test_middleware_installed_on_app(self) -> None:
        from app.api import app
        from app.inbound_auth import InboundAuthMiddleware

        self.assertIn(InboundAuthMiddleware, [m.cls for m in app.user_middleware])


class CurrentUserIdTest(unittest.TestCase):
    def test_disabled_falls_back_to_default(self) -> None:
        from app.api import current_user_id

        with mock.patch("app.config.settings.INBOUND_SERVICE_TOKENS", ""):
            self.assertEqual(current_user_id(None), "default")
            self.assertEqual(current_user_id("  "), "default")
            self.assertEqual(current_user_id("u1"), "u1")

    def test_enabled_requires_user_header(self) -> None:
        from fastapi import HTTPException

        from app.api import current_user_id

        with mock.patch("app.config.settings.INBOUND_SERVICE_TOKENS", _TOKENS):
            with self.assertRaises(HTTPException) as ctx:
                current_user_id(None)
            self.assertEqual(ctx.exception.status_code, 400)
            self.assertEqual(current_user_id("u7"), "u7")

    def test_invalid_user_id_400(self) -> None:
        from fastapi import HTTPException

        from app.api import current_user_id

        for bad in ("../etc", "a" * 33, "u 1"):
            with self.subTest(uid=bad):
                with self.assertRaises(HTTPException) as ctx:
                    current_user_id(bad)
                self.assertEqual(ctx.exception.status_code, 400)


class MigrateDefaultNamespaceTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._patch = mock.patch("app.config.settings.QUANT_CACHE_DIR", self._tmp.name)
        self._patch.start()
        self.users = Path(self._tmp.name) / "users"

    def tearDown(self) -> None:
        self._patch.stop()
        self._tmp.cleanup()

    def _touch(self, rel: str, text: str = "x") -> Path:
        p = self.users / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    def test_moves_all_subdirs_and_removes_empty_default(self) -> None:
        from app.runner import migrate_default_user_namespace

        self._touch("default/strategies/custom/custom_a.py")
        self._touch("default/factors/uf_x.json")
        self._touch("default/mining/candidates.parquet")
        moved = migrate_default_user_namespace("u1")
        self.assertEqual(moved, ["factors", "mining", "strategies"])
        self.assertTrue((self.users / "u1/strategies/custom/custom_a.py").exists())
        self.assertTrue((self.users / "u1/factors/uf_x.json").exists())
        self.assertFalse((self.users / "default").exists())

    def test_existing_target_is_merged_file_by_file(self) -> None:
        """目标已有数据（代码先于配置上线）：不冲突的文件并入，同名文件保留目标版本。"""
        from app.runner import migrate_default_user_namespace

        self._touch("default/strategies/custom/custom_a.py", "old-a")
        self._touch("default/strategies/custom/custom_b.py", "old-b")
        self._touch("default/factors/uf_x.json")
        self._touch("u1/strategies/custom/custom_b.py", "mine")
        moved = migrate_default_user_namespace("u1")
        self.assertEqual(moved, ["factors", "strategies"])
        self.assertEqual((self.users / "u1/strategies/custom/custom_a.py").read_text(), "old-a")
        # 同名冲突：目标用户的版本不被覆盖，default 那份原地保留待人工处理
        self.assertEqual((self.users / "u1/strategies/custom/custom_b.py").read_text(), "mine")
        self.assertEqual((self.users / "default/strategies/custom/custom_b.py").read_text(), "old-b")
        self.assertTrue((self.users / "u1/factors/uf_x.json").exists())
        # 二次执行：冲突项仍原地保留，不报错、不覆盖
        self.assertEqual(migrate_default_user_namespace("u1"), [])
        self.assertEqual((self.users / "u1/strategies/custom/custom_b.py").read_text(), "mine")

    def test_symlinks_are_not_followed(self) -> None:
        import os

        from app.runner import migrate_default_user_namespace

        outside = Path(self._tmp.name) / "outside"
        outside.mkdir()
        (self.users / "default").mkdir(parents=True)
        os.symlink(outside, self.users / "default" / "strategies")
        self.assertEqual(migrate_default_user_namespace("u1"), [])
        self.assertTrue((self.users / "default" / "strategies").is_symlink())
        self.assertFalse((self.users / "u1" / "strategies").exists())

    def test_empty_target_dir_is_not_a_conflict(self) -> None:
        """只读请求自动建出的空目标目录不阻塞迁移（review 回归）。"""
        from app.runner import migrate_default_user_namespace

        self._touch("default/factors/uf_x.json")
        (self.users / "u1" / "factors").mkdir(parents=True)
        self.assertEqual(migrate_default_user_namespace("u1"), ["factors"])
        self.assertTrue((self.users / "u1/factors/uf_x.json").exists())

    def test_idempotent_and_noop_cases(self) -> None:
        from app.runner import migrate_default_user_namespace

        self.assertEqual(migrate_default_user_namespace("u1"), [])  # default 不存在
        self._touch("default/strategies/ai/ai_a.py")
        self.assertEqual(migrate_default_user_namespace("default"), [])  # 目标即自身
        self.assertEqual(migrate_default_user_namespace("u1"), ["strategies"])
        self.assertEqual(migrate_default_user_namespace("u1"), [])  # 二次执行无事发生

    def test_startup_rejects_invalid_target(self) -> None:
        from app.api import _startup

        self._touch("default/strategies/ai/ai_a.py")
        with mock.patch("app.config.settings.QUANT_MIGRATE_DEFAULT_TO", "../evil"):
            _startup()
        self.assertTrue((self.users / "default/strategies/ai/ai_a.py").exists())

    def test_startup_migrates_when_configured(self) -> None:
        from app.api import _startup

        self._touch("default/strategies/ai/ai_a.py")
        with mock.patch("app.config.settings.QUANT_MIGRATE_DEFAULT_TO", "u3"):
            _startup()
        self.assertTrue((self.users / "u3/strategies/ai/ai_a.py").exists())


if __name__ == "__main__":
    unittest.main()
