"""_service_auth 单元测试（DB 全部 mock，覆盖双读/缓存/fail-open/配额/计数）。"""
from __future__ import annotations

import asyncio
import hashlib
import unittest
from datetime import datetime, timezone
from unittest import mock

from fastapi import HTTPException

from app.api import _service_auth as auth


def make_pool_mock(fetch_rows=None, fetchval=None):
    """模拟 asyncpg pool：acquire() 异步上下文管理器 + fetch/fetchval/execute。"""
    conn = mock.AsyncMock()
    conn.fetch = mock.AsyncMock(return_value=fetch_rows or [])
    conn.fetchval = mock.AsyncMock(return_value=fetchval)
    conn.execute = mock.AsyncMock()
    pool = mock.Mock()
    pool.acquire.return_value.__aenter__ = mock.AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = mock.AsyncMock(return_value=False)
    return pool, conn


def make_token_row(
    token_id, token, consumer="quant", quota_limit=None, quota_window="day"
):
    return {
        "id": token_id,
        "token_hash": hashlib.sha256(token.encode()).hexdigest(),
        "consumer": consumer,
        "quota_limit": quota_limit,
        "quota_window": quota_window,
    }


def make_identity(**kwargs):
    defaults = {"name": "anonymous", "authenticated": False, "db_record": None}
    defaults.update(kwargs)
    return auth.ServiceIdentity(**defaults)


def make_db_record(**kwargs):
    defaults = {
        "id": 7,
        "consumer": "quant",
        "quota_limit": None,
        "quota_window": "day",
    }
    defaults.update(kwargs)
    return auth._DbTokenRecord(**defaults)


class ServiceAuthTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # 每个用例隔离进程内缓存与 env 配置
        self._cache_patchers = [
            mock.patch.object(auth, "_db_tokens_cache", None),
            mock.patch.object(auth, "_db_tokens_cached_at", 0.0),
        ]
        for p in self._cache_patchers:
            p.start()
        self.settings_patcher = mock.patch.object(auth.settings, "SERVICE_TOKENS", "")
        self.settings_patcher.start()

    def tearDown(self):
        for p in self._cache_patchers:
            p.stop()
        self.settings_patcher.stop()


class TestEnvOnly(ServiceAuthTestCase):
    """env 单通道：放行 / 拦截 / emergency token 不查库。"""  # env-only 放行/拦截

    async def test_env_unset_allows_anonymous(self):
        with (
            mock.patch.object(auth.settings, "SERVICE_TOKENS", ""),
            mock.patch.object(
                auth, "get_pool", new=mock.AsyncMock(side_effect=Exception("no db"))
            ),
        ):
            identity = await auth.service_identity(None, None)
            self.assertFalse(identity.authenticated)
            self.assertEqual(identity.name, "anonymous")
            # DB 挂掉且 env 未配置：fail-open 放行
            result = await auth.read_access(identity)
            self.assertIs(result, identity)

    async def test_env_token_rejects_missing_token(self):
        with (
            mock.patch.object(auth.settings, "SERVICE_TOKENS", '{"t1": "web-bff"}'),
            mock.patch.object(
                auth, "get_pool", new=mock.AsyncMock(side_effect=Exception("no db"))
            ),
        ):
            identity = await auth.service_identity(None, None)
            with self.assertRaises(HTTPException) as ctx:
                await auth.read_access(identity)
            self.assertEqual(ctx.exception.status_code, 401)
            with self.assertRaises(HTTPException) as ctx:
                await auth.quant_access(identity)
            self.assertEqual(ctx.exception.status_code, 401)

    async def test_env_token_hit_authenticates_without_db(self):
        with (
            mock.patch.object(auth.settings, "SERVICE_TOKENS", '{"t1": "web-bff"}'),
            mock.patch.object(auth, "_db_tokens", new=mock.AsyncMock()) as db_mock,
        ):
            identity = await auth.service_identity("t1", None)
            self.assertTrue(identity.authenticated)
            self.assertEqual(identity.name, "web-bff")
            self.assertIsNone(identity.db_record)
            # emergency 通道不碰 DB（service_identity 内）
            db_mock.assert_not_called()
            # 无配额：read_access 直接放行
            result = await auth.read_access(identity)
            self.assertIs(result, identity)


class TestDbTokens(ServiceAuthTestCase):
    """DB 通道：命中 / 过期 disabled 不出现 / 未启用放行。"""  # DB token 命中

    async def test_db_token_hit_authenticates_and_counts(self):
        row = make_token_row(7, "db-token")
        pool, conn = make_pool_mock(fetch_rows=[row])
        with mock.patch.object(auth, "get_pool", new=mock.AsyncMock(return_value=pool)):
            identity = await auth.service_identity("db-token", None)
            self.assertTrue(identity.authenticated)
            self.assertEqual(identity.name, "quant")
            self.assertIsNotNone(identity.db_record)
            # 计数 UPSERT 以后台任务触发，让它跑完
            await asyncio.sleep(0)
            execute_sql = conn.execute.await_args_list[0].args[0]
            self.assertIn("ON CONFLICT (token_id, window_start)", execute_sql)

    async def test_db_token_unknown_rejected_when_db_has_tokens(self):
        row = make_token_row(7, "db-token")
        pool, _ = make_pool_mock(fetch_rows=[row])
        with mock.patch.object(auth, "get_pool", new=mock.AsyncMock(return_value=pool)):
            identity = await auth.service_identity("wrong-token", None)
            self.assertFalse(identity.authenticated)
            self.assertEqual(identity.name, "unknown")
            with self.assertRaises(HTTPException) as ctx:
                await auth.read_access(identity)
            self.assertEqual(ctx.exception.status_code, 401)

    async def test_disabled_and_expired_tokens_not_loaded(self):
        """disabled/过期 token 由 SQL 过滤，不出现在缓存 -> 拒绝。"""
        # DB 返回空（被 WHERE status/expires_at 过滤后没有记录）
        pool, _ = make_pool_mock(fetch_rows=[])
        with mock.patch.object(auth, "get_pool", new=mock.AsyncMock(return_value=pool)):
            identity = await auth.service_identity("revoked-token", None)
            self.assertFalse(identity.authenticated)

    async def test_db_empty_table_means_auth_disabled(self):
        pool, _ = make_pool_mock(fetch_rows=[])
        with mock.patch.object(auth, "get_pool", new=mock.AsyncMock(return_value=pool)):
            identity = await auth.service_identity(None, "quant")
            self.assertEqual(identity.name, "quant")
            result = await auth.read_access(identity)
            self.assertIs(result, identity)


class TestCache(ServiceAuthTestCase):
    """进程内缓存 TTL 60s。"""  # 缓存 TTL 内不打 DB

    async def test_cache_ttl_avoids_second_db_query(self):
        row = make_token_row(7, "db-token")
        pool, conn = make_pool_mock(fetch_rows=[row])
        with mock.patch.object(auth, "get_pool", new=mock.AsyncMock(return_value=pool)):
            await auth._db_tokens()
            await auth._db_tokens()
            self.assertEqual(conn.fetch.await_count, 1)

    async def test_cache_expired_requeries_db(self):
        row = make_token_row(7, "db-token")
        pool, conn = make_pool_mock(fetch_rows=[row])
        with mock.patch.object(auth, "get_pool", new=mock.AsyncMock(return_value=pool)):
            await auth._db_tokens()
            auth._db_tokens_cached_at -= auth._CACHE_TTL_SECONDS + 1
            await auth._db_tokens()
            self.assertEqual(conn.fetch.await_count, 2)


class TestFailOpen(ServiceAuthTestCase):
    """DB 异常降级。"""  # DB 异常 fail-open

    async def test_db_failure_falls_back_to_stale_cache(self):
        row = make_token_row(7, "db-token")
        pool_ok, _ = make_pool_mock(fetch_rows=[row])
        with mock.patch.object(
            auth, "get_pool", new=mock.AsyncMock(return_value=pool_ok)
        ):
            tokens = await auth._db_tokens()
            self.assertIn(hashlib.sha256(b"db-token").hexdigest(), tokens)
        # TTL 过期后 DB 挂掉：沿用旧缓存，token 仍然有效
        auth._db_tokens_cached_at = 0.0
        with (
            mock.patch.object(
                auth, "get_pool", new=mock.AsyncMock(side_effect=Exception("db down"))
            ),
            mock.patch.object(auth, "_increment_usage", new=mock.AsyncMock()),
        ):
            identity = await auth.service_identity("db-token", None)
            self.assertTrue(identity.authenticated)

    async def test_db_failure_without_cache_treated_as_auth_disabled(self):
        with mock.patch.object(
            auth, "get_pool", new=mock.AsyncMock(side_effect=Exception("db down"))
        ):
            tokens = await auth._db_tokens()
            self.assertIsNone(tokens)
            identity = await auth.service_identity("any-token", None)
            self.assertFalse(identity.authenticated)
            result = await auth.read_access(identity)
            self.assertIs(result, identity)


class TestQuota(ServiceAuthTestCase):
    """配额 429 / Retry-After / fail-open。"""  # 配额超限 429

    async def test_quota_exceeded_raises_429_with_retry_after(self):
        record = make_db_record(quota_limit=5, quota_window="day")
        identity = make_identity(name="quant", authenticated=True, db_record=record)
        pool, _ = make_pool_mock(fetchval=5)
        with mock.patch.object(auth, "get_pool", new=mock.AsyncMock(return_value=pool)):
            with self.assertRaises(HTTPException) as ctx:
                await auth.read_access(identity)
            exc = ctx.exception
            self.assertEqual(exc.status_code, 429)
            self.assertIn("配额", exc.detail)
            retry_after = int(exc.headers["Retry-After"])
            self.assertGreaterEqual(retry_after, 1)
            self.assertLessEqual(retry_after, 86400)

    async def test_quota_under_limit_allows(self):
        record = make_db_record(quota_limit=5, quota_window="hour")
        identity = make_identity(name="quant", authenticated=True, db_record=record)
        pool, conn = make_pool_mock(fetchval=4)
        with mock.patch.object(auth, "get_pool", new=mock.AsyncMock(return_value=pool)):
            result = await auth.quant_access(identity)
            self.assertIs(result, identity)
            sql = conn.fetchval.await_args.args[0]
            self.assertIn("service_token_usage", sql)

    async def test_quota_none_skips_check(self):
        record = make_db_record(quota_limit=None)
        identity = make_identity(name="quant", authenticated=True, db_record=record)
        # quota_limit 为 NULL 时不再为配额查库（缓存加载本身允许）
        with (
            mock.patch.object(auth, "_db_tokens", new=mock.AsyncMock(return_value={})),
            mock.patch.object(
                auth,
                "get_pool",
                new=mock.AsyncMock(side_effect=AssertionError("不应查库")),
            ),
        ):
            result = await auth.read_access(identity)
            self.assertIs(result, identity)

    async def test_quota_check_db_failure_fail_open(self):
        record = make_db_record(quota_limit=1)
        identity = make_identity(name="quant", authenticated=True, db_record=record)
        with mock.patch.object(
            auth, "get_pool", new=mock.AsyncMock(side_effect=Exception("db down"))
        ):
            result = await auth.read_access(identity)
            self.assertIs(result, identity)

    async def test_env_identity_has_no_quota(self):
        identity = make_identity(name="web-bff", authenticated=True, db_record=None)
        with mock.patch.object(auth, "_db_tokens", new=mock.AsyncMock(return_value={})):
            result = await auth.read_access(identity)
            self.assertIs(result, identity)


class TestUsageCounting(ServiceAuthTestCase):
    """计数 fire-and-forget：不阻塞、不抛。"""  # 计数 UPSERT 不阻塞且不抛异常

    async def test_increment_failure_swallowed(self):
        ws = datetime(2026, 9, 12, tzinfo=timezone.utc)
        with mock.patch.object(
            auth, "get_pool", new=mock.AsyncMock(side_effect=Exception("db down"))
        ):
            await auth._increment_usage(1, ws)  # 不抛异常

    async def test_counting_is_fire_and_forget(self):
        """DB token 命中立即返回，不等计数完成。"""
        record = make_db_record()
        started = asyncio.Event()
        release = asyncio.Event()

        async def slow_increment(token_id, window_start):
            started.set()
            await release.wait()

        with (
            mock.patch.object(
                auth,
                "_db_tokens",
                new=mock.AsyncMock(
                    return_value={hashlib.sha256(b"db-token").hexdigest(): record}
                ),
            ),
            mock.patch.object(auth, "_increment_usage", new=slow_increment),
        ):
            identity = await auth.service_identity("db-token", None)
            self.assertTrue(identity.authenticated)
            # 计数任务已启动，但身份返回不等它完成
            await asyncio.sleep(0)
            self.assertTrue(started.is_set())
            release.set()

    async def test_window_alignment(self):
        now = datetime(2026, 9, 12, 15, 37, 42, tzinfo=timezone.utc)
        self.assertEqual(
            auth._window_start("day", now),
            datetime(2026, 9, 12, tzinfo=timezone.utc),
        )
        self.assertEqual(
            auth._window_start("hour", now),
            datetime(2026, 9, 12, 15, tzinfo=timezone.utc),
        )
        self.assertEqual(auth._retry_after_seconds("hour", now), 3600 - 37 * 60 - 42)
        self.assertGreater(auth._retry_after_seconds("day", now), 0)


if __name__ == "__main__":
    unittest.main()
