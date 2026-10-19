"""个人访问令牌 PAT（/api/auth/tokens*）单元测试。

DB 全部 mock（与 test_service_auth 同思路：替换 get_pool 返回假 pool，
acquire() 为异步上下文管理器），这里用内存假库按 SQL 片段分发，
覆盖签发 / 列表 / 撤销 / verify 全部分支：名单、上限、过期、撤销、
用户禁用、非 mcp 调用 verify 403、库里只存哈希、last_used_at 节流。
经 httpx ASGITransport 走真实路由与依赖链（read_access / session_user）。
"""
from __future__ import annotations

import hashlib
import importlib
import itertools
import logging
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

try:
    import fastapi  # noqa: F401
    import httpx
except ImportError:  # 沙箱可能未装，跳过相关用例
    fastapi = None
    httpx = None

if fastapi is not None:
    from fastapi import FastAPI

    from app import config as config_module
    from app.api import _service_auth, auth, auth_tokens

SESSION_A = "session-token-a"
SESSION_B = "session-token-b"
SESSION_DISABLED = "session-token-disabled"
SESSION_EXPIRED = "session-token-expired"


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class _Transaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeAuthDB:
    """auth schema 的内存假库：只实现 auth.py / auth_tokens.py 用到的语句。"""

    def __init__(self):
        now = datetime.now(timezone.utc)
        self.users = {
            1: {"id": 1, "email": "a@x", "display_name": "A", "role": "admin", "status": "active"},
            2: {"id": 2, "email": "b@x", "display_name": "B", "role": "user", "status": "active"},
            3: {"id": 3, "email": "c@x", "display_name": None, "role": "user", "status": "disabled"},
        }
        self.sessions = {
            _sha(SESSION_A): {"id": 11, "user_id": 1, "expires_at": now + timedelta(days=1)},
            _sha(SESSION_B): {"id": 12, "user_id": 2, "expires_at": now + timedelta(days=1)},
            _sha(SESSION_DISABLED): {"id": 13, "user_id": 3, "expires_at": now + timedelta(days=1)},
            _sha(SESSION_EXPIRED): {"id": 14, "user_id": 1, "expires_at": now - timedelta(seconds=1)},
        }
        self.tokens: dict[int, dict] = {}
        self._ids = itertools.count(1)
        self.last_used_updates = 0
        self.fail_last_used_update = False
        self.locked_users: list[int] = []

    # ---- 测试辅助 ----

    def add_token(self, user_id=1, *, token=None, scopes=("backtest",), created_at=None,
                  expires_at=None, revoked_at=None, last_used_at=None, name="seed"):
        now = datetime.now(timezone.utc)
        token_id = next(self._ids)
        token = token or f"tdk_pat_seed{token_id:040d}"
        self.tokens[token_id] = {
            "id": token_id,
            "user_id": user_id,
            "name": name,
            "token_prefix": token[:12],
            "token_hash": _sha(token),
            "scopes": list(scopes),
            "created_at": created_at or now + timedelta(microseconds=token_id),
            "expires_at": expires_at or now + timedelta(days=30),
            "last_used_at": last_used_at,
            "revoked_at": revoked_at,
        }
        return token_id, token

    def pool(self):
        conn = _FakeConn(self)
        pool = mock.Mock()
        pool.acquire.return_value.__aenter__ = mock.AsyncMock(return_value=conn)
        pool.acquire.return_value.__aexit__ = mock.AsyncMock(return_value=False)
        return pool


class _FakeConn:
    def __init__(self, db: FakeAuthDB):
        self.db = db

    def transaction(self):
        return _Transaction()

    async def fetchrow(self, sql: str, *args):
        db = self.db
        if "FROM auth.sessions s" in sql:
            session = db.sessions.get(args[0])
            if session is None:
                return None
            user = db.users[session["user_id"]]
            return {"session_id": session["id"], "expires_at": session["expires_at"], **user}
        if "INSERT INTO auth.api_tokens" in sql:
            user_id, name, prefix, token_hash, scopes, expires_at = args
            token_id = next(db._ids)
            row = {
                "id": token_id,
                "user_id": user_id,
                "name": name,
                "token_prefix": prefix,
                "token_hash": token_hash,
                "scopes": list(scopes),
                "created_at": datetime.now(timezone.utc),
                "expires_at": expires_at,
                "last_used_at": None,
                "revoked_at": None,
            }
            db.tokens[token_id] = row
            return dict(row)
        if "SET revoked_at" in sql:
            token_id, user_id = args
            row = db.tokens.get(token_id)
            if row is None or row["user_id"] != user_id:
                return None
            row["revoked_at"] = row["revoked_at"] or datetime.now(timezone.utc)
            return {"id": token_id}
        if "FROM auth.api_tokens t" in sql:
            for row in db.tokens.values():
                if row["token_hash"] == args[0]:
                    return {**row, "user_status": db.users[row["user_id"]]["status"]}
            return None
        raise AssertionError(f"未预期的 fetchrow SQL: {sql}")

    async def fetch(self, sql: str, *args):
        if "FROM auth.api_tokens" in sql:
            user_id, limit = args
            assert "ORDER BY (revoked_at IS NULL AND expires_at > now()) DESC" in sql
            now = datetime.now(timezone.utc)
            rows = [dict(r) for r in self.db.tokens.values() if r["user_id"] == user_id]
            # 与真实 SQL 同序：有效令牌在前，组内新的在前
            rows.sort(
                key=lambda r: (
                    r["revoked_at"] is None and r["expires_at"] > now,
                    r["created_at"],
                    r["id"],
                ),
                reverse=True,
            )
            return rows[:limit]
        raise AssertionError(f"未预期的 fetch SQL: {sql}")

    async def fetchval(self, sql: str, *args):
        if "count(*) FROM auth.api_tokens" in sql:
            now = datetime.now(timezone.utc)
            return sum(
                1
                for r in self.db.tokens.values()
                if r["user_id"] == args[0] and r["revoked_at"] is None and r["expires_at"] > now
            )
        raise AssertionError(f"未预期的 fetchval SQL: {sql}")

    async def execute(self, sql: str, *args):
        db = self.db
        if "SET last_used_at" in sql:
            if db.fail_last_used_update:
                raise RuntimeError("db write failed")
            token_id, threshold = args
            row = db.tokens[token_id]
            if row["last_used_at"] is None or row["last_used_at"] < threshold:
                row["last_used_at"] = datetime.now(timezone.utc)
                db.last_used_updates += 1
            return "UPDATE 1"
        if "FROM auth.users WHERE id = $1 FOR UPDATE" in sql:
            db.locked_users.append(args[0])
            return "SELECT 1"
        if "DELETE FROM auth.sessions" in sql or "auth.sessions SET last_seen_at" in sql:
            return "OK"
        raise AssertionError(f"未预期的 execute SQL: {sql}")


@unittest.skipIf(fastapi is None or httpx is None, "fastapi/httpx 未安装（沙箱缺依赖）")
class AuthTokensTestCase(unittest.IsolatedAsyncioTestCase):
    """公共夹具：只挂 auth + auth_tokens 路由的最小 app（不触发 lifespan）。"""

    service_tokens = ""

    async def asyncSetUp(self):
        self.db = FakeAuthDB()
        get_pool = mock.AsyncMock(side_effect=lambda: self.db.pool())
        self._patchers = [
            mock.patch.object(auth, "get_pool", new=get_pool),
            mock.patch.object(auth_tokens, "get_pool", new=get_pool),
            # 服务令牌：只走 env 通道，DB 通道视为空表（未启用）
            mock.patch.object(_service_auth, "_db_tokens", new=mock.AsyncMock(return_value={})),
            mock.patch.object(_service_auth.settings, "SERVICE_TOKENS", self.service_tokens),
            # None = 名单未配置（所有登录用户可用）；frozenset() 表示「配置了但为空 = 全拒」
            mock.patch.object(auth_tokens.settings, "PAT_ALLOWED_USER_IDS", None),
        ]
        for p in self._patchers:
            p.start()
        app = FastAPI()
        app.include_router(auth.router)
        app.include_router(auth_tokens.router)
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        )

    async def asyncTearDown(self):
        await self.client.aclose()
        for p in reversed(self._patchers):
            p.stop()

    async def create(self, session=SESSION_A, **body):
        payload = {"name": "my agent", "scopes": ["strategy:read", "backtest"]}
        payload.update(body)
        return await self.client.post(
            "/api/auth/tokens", json=payload, headers={"X-Session-Token": session}
        )

    async def list_tokens(self, session=SESSION_A):
        return await self.client.get(
            "/api/auth/tokens", headers={"X-Session-Token": session}
        )

    async def revoke(self, token_id, session=SESSION_A):
        return await self.client.delete(
            f"/api/auth/tokens/{token_id}", headers={"X-Session-Token": session}
        )

    async def verify(self, token, service_token=None):
        headers = {"X-Service-Token": service_token} if service_token else {}
        return await self.client.post(
            "/api/auth/tokens/verify", json={"token": token}, headers=headers
        )


class TestCreateToken(AuthTokensTestCase):
    async def test_create_returns_plaintext_once_and_stores_hash_only(self):
        res = await self.create()
        self.assertEqual(res.status_code, 201)
        data = res.json()
        token = data["token"]
        self.assertTrue(token.startswith("tdk_pat_"))
        self.assertGreater(len(token), 40)
        self.assertEqual(data["token_prefix"], token[:12])
        self.assertEqual(data["scopes"], ["strategy:read", "backtest"])
        self.assertEqual(data["name"], "my agent")
        self.assertEqual(
            set(data), {"id", "name", "token", "token_prefix", "scopes", "created_at", "expires_at"}
        )
        # 默认 90 天有效
        expires_at = datetime.fromisoformat(data["expires_at"])
        delta = expires_at - datetime.now(timezone.utc)
        self.assertTrue(timedelta(days=89, hours=23) < delta <= timedelta(days=90))

        stored = self.db.tokens[data["id"]]
        self.assertEqual(stored["token_hash"], _sha(token))
        # 计数前锁本人用户行（串行化并发签发，防绕过上限）
        self.assertEqual(self.db.locked_users, [1])
        # 库里任何字段都不含明文
        for value in stored.values():
            self.assertNotEqual(value, token)
            if isinstance(value, str):
                self.assertNotIn(token, value)

        # 列表不再返回明文与哈希
        listed = (await self.list_tokens()).json()
        self.assertEqual(len(listed), 1)
        self.assertNotIn("token", listed[0])
        self.assertNotIn("token_hash", listed[0])

    async def test_scopes_deduplicated_and_canonical_order(self):
        res = await self.create(
            scopes=["backtest", "strategy:write", "backtest", "strategy:read"], expires_days=30
        )
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.json()["scopes"], ["strategy:read", "strategy:write", "backtest"])
        delta = datetime.fromisoformat(res.json()["expires_at"]) - datetime.now(timezone.utc)
        self.assertTrue(timedelta(days=29, hours=23) < delta <= timedelta(days=30))

    async def test_invalid_body_rejected(self):
        for body in (
            {"name": ""},
            {"name": "   "},
            {"name": "x" * 65},
            {"scopes": []},
            {"scopes": ["admin"]},
            {"scopes": ["backtest", "strategy:delete"]},
            {"expires_days": 0},
            {"expires_days": 366},
        ):
            with self.subTest(body=body):
                res = await self.create(**body)
                self.assertEqual(res.status_code, 422)
        self.assertEqual(self.db.tokens, {})

    async def test_session_required(self):
        for session in ("bogus", SESSION_EXPIRED, SESSION_DISABLED):
            with self.subTest(session=session):
                res = await self.create(session=session)
                self.assertEqual(res.status_code, 401)
        res = await self.client.post(
            "/api/auth/tokens", json={"name": "x", "scopes": ["backtest"]}
        )
        self.assertEqual(res.status_code, 422)  # 缺 X-Session-Token 头
        self.assertEqual(self.db.tokens, {})

    async def test_identity_only_from_session(self):
        # 请求体多余字段（user_id）与伪造的 X-User-Id 头都被忽略，归属只看 session
        res = await self.client.post(
            "/api/auth/tokens",
            json={"name": "x", "scopes": ["backtest"], "user_id": 2, "id": 999},
            headers={"X-Session-Token": SESSION_A, "X-User-Id": "u2"},
        )
        self.assertEqual(res.status_code, 201)
        self.assertEqual(self.db.tokens[res.json()["id"]]["user_id"], 1)
        other_id, _ = self.db.add_token(2)
        res = await self.client.delete(
            f"/api/auth/tokens/{other_id}",
            headers={"X-Session-Token": SESSION_A, "X-User-Id": "u2"},
        )
        self.assertEqual(res.status_code, 404)
        self.assertIsNone(self.db.tokens[other_id]["revoked_at"])
        listed = await self.client.get(
            "/api/auth/tokens", headers={"X-Session-Token": SESSION_A, "X-User-Id": "u2"}
        )
        self.assertNotIn(other_id, [i["id"] for i in listed.json()])

    async def test_allowlist_blocks_other_users(self):
        with mock.patch.object(auth_tokens.settings, "PAT_ALLOWED_USER_IDS", frozenset({2})):
            res = await self.create(session=SESSION_A)
            self.assertEqual(res.status_code, 403)
            res = await self.create(session=SESSION_B)
            self.assertEqual(res.status_code, 201)
        self.assertEqual([t["user_id"] for t in self.db.tokens.values()], [2])

    async def test_allowlist_configured_but_all_invalid_is_fail_closed(self):
        # 误写成 quant 口径（u1）等全部非法：解析为空集合 = 拒绝所有人，
        # 不能退化成「未配置 = 全部放行」
        with self.assertLogs(config_module.logger, level=logging.WARNING):
            allowed = config_module._parse_user_ids("u1,u2", "PAT_ALLOWED_USER_IDS")
        self.assertEqual(allowed, frozenset())
        with mock.patch.object(auth_tokens.settings, "PAT_ALLOWED_USER_IDS", allowed):
            for session in (SESSION_A, SESSION_B):
                with self.subTest(session=session):
                    self.assertEqual((await self.create(session=session)).status_code, 403)
        self.assertEqual(self.db.tokens, {})

    async def test_active_token_limit(self):
        now = datetime.now(timezone.utc)
        # 已撤销 / 已过期的不计入上限
        self.db.add_token(1, revoked_at=now)
        self.db.add_token(1, expires_at=now - timedelta(seconds=1))
        for _ in range(5):
            self.assertEqual((await self.create()).status_code, 201)
        res = await self.create()
        self.assertEqual(res.status_code, 409)
        self.assertIn("上限", res.json()["detail"])
        # 他人不受影响
        self.assertEqual((await self.create(session=SESSION_B)).status_code, 201)
        # 撤销一个后可再签发
        active_id = next(
            t["id"] for t in self.db.tokens.values() if t["user_id"] == 1 and t["revoked_at"] is None
            and t["expires_at"] > now
        )
        self.assertEqual((await self.revoke(active_id)).status_code, 200)
        self.assertEqual((await self.create()).status_code, 201)


class TestListAndRevoke(AuthTokensTestCase):
    async def test_list_own_tokens_newest_first_with_status(self):
        now = datetime.now(timezone.utc)
        old_id, _ = self.db.add_token(1, name="old", created_at=now - timedelta(days=3),
                                      expires_at=now - timedelta(days=1))
        mid_id, _ = self.db.add_token(1, name="mid", created_at=now - timedelta(days=2),
                                      revoked_at=now - timedelta(days=1))
        new_id, _ = self.db.add_token(1, name="new", created_at=now - timedelta(days=1),
                                      last_used_at=now)
        self.db.add_token(2, name="other")

        res = await self.list_tokens()
        self.assertEqual(res.status_code, 200)
        items = res.json()
        self.assertEqual([i["id"] for i in items], [new_id, mid_id, old_id])
        self.assertEqual([i["status"] for i in items], ["active", "revoked", "expired"])
        self.assertIsNotNone(items[0]["last_used_at"])
        self.assertIsNone(items[2]["last_used_at"])
        self.assertIsNotNone(items[1]["revoked_at"])
        for item in items:
            self.assertEqual(
                set(item),
                {"id", "name", "token_prefix", "scopes", "created_at", "expires_at",
                 "last_used_at", "revoked_at", "status"},
            )

    async def test_list_limit_keeps_active_tokens(self):
        now = datetime.now(timezone.utc)
        active_id, _ = self.db.add_token(1, name="old-active", created_at=now - timedelta(days=200))
        for i in range(auth_tokens._LIST_LIMIT + 5):
            self.db.add_token(1, name=f"revoked-{i}", created_at=now - timedelta(minutes=i),
                              revoked_at=now)
        items = (await self.list_tokens()).json()
        self.assertEqual(len(items), auth_tokens._LIST_LIMIT)
        # 有效令牌排在最前，截断后仍可在页面上撤销
        self.assertEqual(items[0]["id"], active_id)
        self.assertEqual(items[0]["status"], "active")
        self.assertTrue(all(i["status"] == "revoked" for i in items[1:]))

    async def test_list_empty(self):
        res = await self.list_tokens(session=SESSION_B)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), [])

    async def test_list_requires_session(self):
        self.assertEqual((await self.list_tokens(session="bogus")).status_code, 401)

    async def test_revoke_own_token(self):
        token_id, _ = self.db.add_token(1)
        res = await self.revoke(token_id)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), {"revoked": True, "id": token_id})
        first_revoked_at = self.db.tokens[token_id]["revoked_at"]
        self.assertIsNotNone(first_revoked_at)
        # 重复撤销幂等，保留首次时间
        self.assertEqual((await self.revoke(token_id)).status_code, 200)
        self.assertEqual(self.db.tokens[token_id]["revoked_at"], first_revoked_at)
        listed = (await self.list_tokens()).json()
        self.assertEqual(listed[0]["status"], "revoked")

    async def test_revoke_others_or_missing_is_404(self):
        other_id, _ = self.db.add_token(2)
        res = await self.revoke(other_id, session=SESSION_A)
        self.assertEqual(res.status_code, 404)
        self.assertIsNone(self.db.tokens[other_id]["revoked_at"])
        missing = await self.revoke(9999)
        self.assertEqual(missing.status_code, 404)
        # 与不存在同文案，不泄露存在性
        self.assertEqual(res.json(), missing.json())

    async def test_revoke_invalid_id(self):
        self.assertEqual((await self.revoke(0)).status_code, 422)
        self.assertEqual((await self.revoke("abc")).status_code, 422)
        self.assertEqual((await self.revoke(2**63)).status_code, 422)
        self.assertEqual((await self.revoke(1, session="bogus")).status_code, 401)


class TestVerifyDevMode(AuthTokensTestCase):
    """SERVICE_TOKENS 未配置（dev）：verify 匿名放行。"""

    async def test_verify_success(self):
        created = (await self.create(scopes=["strategy:write", "backtest"])).json()
        res = await self.verify(created["token"])
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(
            data,
            {
                "user_id": "u1",
                "scopes": ["strategy:write", "backtest"],
                "expires_at": created["expires_at"],
                "token_id": created["id"],
            },
        )
        datetime.fromisoformat(data["expires_at"])  # ISO8601
        self.assertIsNotNone(self.db.tokens[created["id"]]["last_used_at"])
        self.assertEqual(self.db.last_used_updates, 1)

    async def test_last_used_throttled_to_once_per_minute(self):
        token_id, token = self.db.add_token(1)
        for _ in range(3):
            self.assertEqual((await self.verify(token)).status_code, 200)
        self.assertEqual(self.db.last_used_updates, 1)
        # 上次记录早于 60 秒前：再次更新
        self.db.tokens[token_id]["last_used_at"] = datetime.now(timezone.utc) - timedelta(seconds=61)
        self.assertEqual((await self.verify(token)).status_code, 200)
        self.assertEqual(self.db.last_used_updates, 2)

    async def test_last_used_update_failure_does_not_affect_response(self):
        _, token = self.db.add_token(1)
        self.db.fail_last_used_update = True
        with self.assertLogs(auth_tokens.logger, level=logging.WARNING):
            res = await self.verify(token)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["user_id"], "u1")

    async def test_invalid_tokens_all_401_with_same_detail(self):
        now = datetime.now(timezone.utc)
        _, revoked = self.db.add_token(1, revoked_at=now)
        _, expired = self.db.add_token(1, expires_at=now - timedelta(seconds=1))
        _, disabled_user = self.db.add_token(3)
        cases = {
            "不存在": "tdk_pat_" + "x" * 43,
            "非 PAT 前缀": "session-token-a",
            "已撤销": revoked,
            "已过期": expired,
            "用户禁用": disabled_user,
        }
        details = set()
        for label, token in cases.items():
            with self.subTest(case=label):
                res = await self.verify(token)
                self.assertEqual(res.status_code, 401)
                details.add(res.json()["detail"])
        self.assertEqual(len(details), 1)
        self.assertEqual(self.db.last_used_updates, 0)

    async def test_user_outside_allowlist_rejected(self):
        _, token = self.db.add_token(1)
        with mock.patch.object(auth_tokens.settings, "PAT_ALLOWED_USER_IDS", frozenset({2})):
            res = await self.verify(token)
        self.assertEqual(res.status_code, 401)
        self.assertEqual(res.json()["detail"], auth_tokens._VERIFY_FAILED_DETAIL)
        # 名单放开后同一令牌恢复可用
        self.assertEqual((await self.verify(token)).status_code, 200)

    async def test_revoked_after_issue_rejected(self):
        created = (await self.create()).json()
        self.assertEqual((await self.verify(created["token"])).status_code, 200)
        await self.revoke(created["id"])
        self.assertEqual((await self.verify(created["token"])).status_code, 401)

    async def test_malformed_tokens_are_401_without_db_lookup(self):
        lookups = []
        original = _FakeConn.fetchrow

        async def spy(conn, sql, *args):
            if "FROM auth.api_tokens t" in sql:
                lookups.append(args)
            return await original(conn, sql, *args)

        with mock.patch.object(_FakeConn, "fetchrow", spy):
            for token in ("", "   ", "x" * 257, "tdk_pat_" + "a" * 300):
                with self.subTest(token=token[:20]):
                    res = await self.verify(token)
                    self.assertEqual(res.status_code, 401)
                    self.assertEqual(res.json()["detail"], auth_tokens._VERIFY_FAILED_DETAIL)
        # 形状不合法的输入不进哈希与查库
        self.assertEqual(lookups, [])

    async def test_invalid_body(self):
        res = await self.client.post("/api/auth/tokens/verify", json={})
        self.assertEqual(res.status_code, 422)
        res = await self.client.post("/api/auth/tokens/verify", json={"token": 123})
        self.assertEqual(res.status_code, 422)
        res = await self.client.post(
            "/api/auth/tokens/verify",
            json={"token": "x" * (auth_tokens._VERIFY_BODY_MAX_LEN + 1)},
        )
        self.assertEqual(res.status_code, 422)


class TestVerifyServiceAuth(AuthTokensTestCase):
    """SERVICE_TOKENS 已配置：只有 mcp 可调 verify。"""

    service_tokens = '{"web-token": "web-bff", "mcp-token": "mcp"}'

    async def test_mcp_consumer_allowed(self):
        _, token = self.db.add_token(2, scopes=("strategy:read",))
        res = await self.verify(token, service_token="mcp-token")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["user_id"], "u2")
        self.assertEqual(res.json()["scopes"], ["strategy:read"])

    async def test_non_mcp_consumer_forbidden(self):
        _, token = self.db.add_token(1)
        res = await self.verify(token, service_token="web-token")
        self.assertEqual(res.status_code, 403)
        # 403 发生在查令牌之前：不触碰 last_used_at
        self.assertIsNone(self.db.tokens[1]["last_used_at"])

    async def test_missing_service_token_unauthorized(self):
        _, token = self.db.add_token(1)
        res = await self.verify(token)
        self.assertEqual(res.status_code, 401)
        res = await self.verify(token, service_token="wrong")
        self.assertEqual(res.status_code, 401)

    async def test_self_reported_service_name_not_trusted(self):
        _, token = self.db.add_token(1)
        res = await self.client.post(
            "/api/auth/tokens/verify",
            json={"token": token},
            headers={"X-Service-Name": "mcp"},
        )
        self.assertEqual(res.status_code, 401)

    async def test_web_bff_can_still_manage_tokens(self):
        res = await self.client.post(
            "/api/auth/tokens",
            json={"name": "x", "scopes": ["backtest"]},
            headers={"X-Session-Token": SESSION_A, "X-Service-Token": "web-token"},
        )
        self.assertEqual(res.status_code, 201)
        # 无服务令牌：管理端点同样被 read_access 拦下
        self.assertEqual((await self.list_tokens()).status_code, 401)


class TestVerifyDbServiceChannel(AuthTokensTestCase):
    """env SERVICE_TOKENS 为空、DB service_tokens 通道认证：消费方同样必须是 mcp。"""

    async def asyncSetUp(self):
        await super().asyncSetUp()
        records = {
            _sha("db-quant-token"): _service_auth._DbTokenRecord(
                id=21, consumer="quant", quota_limit=None, quota_window="day"
            ),
            _sha("db-mcp-token"): _service_auth._DbTokenRecord(
                id=22, consumer="mcp", quota_limit=None, quota_window="day"
            ),
        }
        self._db_patchers = [
            mock.patch.object(_service_auth, "_db_tokens", new=mock.AsyncMock(return_value=records)),
            # 用量计数是 fire-and-forget 写库，测试里替换掉
            mock.patch.object(_service_auth, "_increment_usage", new=mock.AsyncMock()),
        ]
        for p in self._db_patchers:
            p.start()

    async def asyncTearDown(self):
        for p in reversed(self._db_patchers):
            p.stop()
        await super().asyncTearDown()

    async def test_db_non_mcp_consumer_forbidden(self):
        _, token = self.db.add_token(1)
        res = await self.verify(token, service_token="db-quant-token")
        self.assertEqual(res.status_code, 403)
        self.assertIsNone(self.db.tokens[1]["last_used_at"])

    async def test_db_mcp_consumer_allowed(self):
        _, token = self.db.add_token(1)
        res = await self.verify(token, service_token="db-mcp-token")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["user_id"], "u1")
        # router 级与端点级都声明了 read_access：依赖缓存保证只识别一次，
        # DB 令牌用量只计 1 次（不重复计数）
        _service_auth._increment_usage.assert_called_once()

    async def test_db_channel_enabled_requires_service_token(self):
        _, token = self.db.add_token(1)
        self.assertEqual((await self.verify(token)).status_code, 401)
        self.assertEqual((await self.verify(token, service_token="wrong")).status_code, 401)


class TestSessionEndpointUnchanged(AuthTokensTestCase):
    """抽取 validate_session 后 /api/auth/session 行为不变。"""

    async def test_session_ok(self):
        res = await self.client.post(
            "/api/auth/session", headers={"X-Session-Token": SESSION_A}
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(
            data["user"], {"id": 1, "email": "a@x", "display_name": "A", "role": "admin"}
        )
        datetime.fromisoformat(data["expires_at"])

    async def test_session_invalid(self):
        for session in ("bogus", SESSION_EXPIRED, SESSION_DISABLED):
            with self.subTest(session=session):
                res = await self.client.post(
                    "/api/auth/session", headers={"X-Session-Token": session}
                )
                self.assertEqual(res.status_code, 401)
                self.assertEqual(res.json()["detail"], "会话无效或已过期")


@unittest.skipIf(fastapi is None, "fastapi 未安装（沙箱缺依赖）")
class TestPatConfigAndSchema(unittest.TestCase):
    def test_parse_allowed_user_ids(self):
        with self.assertLogs(config_module.logger, level=logging.WARNING) as logs:
            ids = config_module._parse_user_ids(" 1, 2,abc,,-3,0, 2 ", "PAT_ALLOWED_USER_IDS")
        self.assertEqual(ids, frozenset({1, 2}))
        self.assertEqual(len(logs.records), 3)  # abc / -3 / 0
        # 未配置（空串 / 只有空白与逗号）= None（不启用名单）
        self.assertIsNone(config_module._parse_user_ids("", "X"))
        self.assertIsNone(config_module._parse_user_ids(" , ,", "X"))

    def test_settings_reads_env(self):
        with mock.patch.dict("os.environ", {"PAT_ALLOWED_USER_IDS": "5,7"}):
            self.assertEqual(config_module.Settings().PAT_ALLOWED_USER_IDS, frozenset({5, 7}))
        with mock.patch.dict("os.environ", {"PAT_ALLOWED_USER_IDS": ""}):
            self.assertIsNone(config_module.Settings().PAT_ALLOWED_USER_IDS)
        with mock.patch.dict("os.environ", {"PAT_ALLOWED_USER_IDS": "u1"}):
            self.assertEqual(config_module.Settings().PAT_ALLOWED_USER_IDS, frozenset())

    def test_schema_ddl_in_sync_with_init_sql(self):
        auth_main = importlib.import_module("app.auth_main")
        init_sql = (Path(__file__).resolve().parents[1] / "init.sql").read_text(encoding="utf-8")
        start = auth_main._SCHEMA_DDL.index("CREATE TABLE IF NOT EXISTS auth.api_tokens")
        block = auth_main._SCHEMA_DDL[start:].strip()
        self.assertIn("idx_auth_api_tokens_user_id ON auth.api_tokens (user_id)", block)
        self.assertIn("token_hash TEXT NOT NULL UNIQUE", block)
        self.assertIn(block, init_sql)

    def test_routes_registered(self):
        auth_main = importlib.import_module("app.auth_main")
        routes = set()
        stack = list(auth_main.app.routes)
        while stack:
            route = stack.pop()
            path = getattr(route, "path", None)
            if path is not None:
                for method in getattr(route, "methods", None) or ():
                    routes.add((method, path))
            inner = getattr(route, "original_router", None)
            if inner is not None:
                stack.extend(getattr(inner, "routes", []))
        for expected in (
            ("POST", "/api/auth/tokens"),
            ("GET", "/api/auth/tokens"),
            ("DELETE", "/api/auth/tokens/{token_id}"),
            ("POST", "/api/auth/tokens/verify"),
        ):
            self.assertIn(expected, routes)


if __name__ == "__main__":
    unittest.main()
