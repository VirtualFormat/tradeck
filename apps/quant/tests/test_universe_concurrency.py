"""缺陷 2 修复验收：universe TTL 缓存的并发去抖（单飞）+ 失败负缓存。

覆盖点：
- TTL 过期瞬间 N 个并发协程只触发一次 /api/universe 请求（per-market
  asyncio.Lock 单飞，锁内二次检查吃先到者的缓存）；
- 拉取失败（空响应 / 抛异常）写短 TTL（60s）负缓存：TTL 内重复调用不再
  请求，直接走 tracked 子集 fallback；
- 负缓存短 TTL 到期后允许重试（源恢复即可自愈，不会永久钉死 fallback）；
- 正缓存路径不回退（回归保护）。

fallback 路径经 app.jobs（依赖 polars），负缓存用例缺依赖时 skip；
单飞去抖用例不触 fallback，无依赖要求。
"""
from __future__ import annotations

import asyncio
import time
import unittest
from unittest import mock

try:
    import polars  # noqa: F401

    _HAS_DEPS = True
except ModuleNotFoundError:  # 本机无 polars：fallback 用例 skip
    _HAS_DEPS = False

import app.universe as universe_mod


def _clear_cache() -> None:
    """清空进程内缓存与锁（用例间隔离，防污染其他测试文件）。"""
    universe_mod._universe_cache.clear()
    universe_mod._market_locks.clear()


class UniverseSingleFlightTest(unittest.TestCase):
    def setUp(self) -> None:
        _clear_cache()
        self.addCleanup(_clear_cache)

    def test_concurrent_calls_hit_api_once(self) -> None:
        """TTL 过期瞬间并发 8 个协程，只有 1 个真正打 /api/universe。"""
        calls = 0

        async def fake_fetch(market: str) -> list[str]:
            nonlocal calls
            calls += 1
            await asyncio.sleep(0.05)  # 模拟网络延迟，让并发协程都撞上锁
            return ["600519.SH", "000001.SZ"]

        async def run():
            with mock.patch.object(
                universe_mod, "_fetch_market_symbols", side_effect=fake_fetch
            ):
                results = await asyncio.gather(
                    *(universe_mod._market_symbols("CN") for _ in range(8))
                )
            return results

        results = asyncio.run(run())
        self.assertEqual(calls, 1)  # 单飞：只打一次
        for r in results:
            self.assertEqual(r, ["600519.SH", "000001.SZ"])

    def test_concurrent_calls_on_expired_cache_hit_api_once(self) -> None:
        """缓存过期（旧时间戳）后的并发窗口同样只放行一个请求。"""
        universe_mod._universe_cache["CN"] = (
            time.monotonic() - universe_mod._UNIVERSE_CACHE_TTL_SEC - 1,
            ["OLD.SH"],
            False,
        )
        calls = 0

        async def fake_fetch(market: str) -> list[str]:
            nonlocal calls
            calls += 1
            await asyncio.sleep(0.05)
            return ["600519.SH"]

        async def run():
            with mock.patch.object(
                universe_mod, "_fetch_market_symbols", side_effect=fake_fetch
            ):
                return await asyncio.gather(
                    *(universe_mod._market_symbols("CN") for _ in range(6))
                )

        results = asyncio.run(run())
        self.assertEqual(calls, 1)
        for r in results:
            self.assertEqual(r, ["600519.SH"])


@unittest.skipUnless(_HAS_DEPS, "缺 polars（fallback 路径依赖 app.jobs）")
class UniverseNegativeCacheTest(unittest.TestCase):
    def setUp(self) -> None:
        _clear_cache()
        self.addCleanup(_clear_cache)

    def test_failure_writes_negative_cache_no_retry_within_ttl(self) -> None:
        """拉取为空 → 负缓存；60s TTL 内重复调用不再请求，直接 fallback。"""
        calls = 0

        async def fake_fetch(market: str) -> list[str]:
            nonlocal calls
            calls += 1
            return []  # 源无数据（不可达/空响应）

        async def run():
            with mock.patch.object(
                universe_mod, "_fetch_market_symbols", side_effect=fake_fetch
            ):
                first = await universe_mod._market_symbols("CN")
                second = await universe_mod._market_symbols("CN")
                third = await universe_mod._market_symbols("CN")
            return first, second, third

        first, second, third = asyncio.run(run())
        self.assertEqual(calls, 1)  # 负缓存生效：后两次没再请求
        # 三次都走 tracked 子集 fallback
        tracked = universe_mod._tracked()
        cn_subset = [s for s in tracked if universe_mod._market_of(s) == "cn"]
        for r in (first, second, third):
            self.assertEqual(r, cn_subset)
        # 负缓存标记已写
        _, symbols, is_negative = universe_mod._universe_cache["CN"]
        self.assertTrue(is_negative)
        self.assertEqual(symbols, [])

    def test_exception_also_negative_cached(self) -> None:
        """拉取抛异常同样记负缓存（双保险：client 约定不抛，但这里兜住）。"""
        calls = 0

        async def fake_fetch(market: str) -> list[str]:
            nonlocal calls
            calls += 1
            raise TimeoutError("read timeout")

        async def run():
            with mock.patch.object(
                universe_mod, "_fetch_market_symbols", side_effect=fake_fetch
            ):
                await universe_mod._market_symbols("CN")
                return await universe_mod._market_symbols("CN")

        result = asyncio.run(run())
        self.assertEqual(calls, 1)  # 第二次走负缓存没再请求
        cn_subset = [
            s for s in universe_mod._tracked()
            if universe_mod._market_of(s) == "cn"
        ]
        self.assertEqual(result, cn_subset)

    def test_negative_cache_expires_and_retries(self) -> None:
        """负缓存按短 TTL（60s）过期后允许重试（源恢复即自愈）。"""
        calls = 0

        async def fake_fetch(market: str) -> list[str]:
            nonlocal calls
            calls += 1
            return ["600519.SH"] if calls > 1 else []

        async def run():
            with mock.patch.object(
                universe_mod, "_fetch_market_symbols", side_effect=fake_fetch
            ):
                await universe_mod._market_symbols("CN")  # 失败 → 负缓存
                # 人为把负缓存时间戳拨回短 TTL 之前（等价于等 61s）
                _, symbols, neg = universe_mod._universe_cache["CN"]
                universe_mod._universe_cache["CN"] = (
                    time.monotonic()
                    - universe_mod._UNIVERSE_NEGATIVE_TTL_SEC
                    - 1,
                    symbols,
                    neg,
                )
                return await universe_mod._market_symbols("CN")  # 应重试成功

        result = asyncio.run(run())
        self.assertEqual(calls, 2)  # 过期后重试了一次
        self.assertEqual(result, ["600519.SH"])  # 源恢复 → 用真数据
        _, _, is_negative = universe_mod._universe_cache["CN"]
        self.assertFalse(is_negative)  # 已转正缓存

    def test_positive_cache_not_falling_back(self) -> None:
        """回归保护：正缓存 TTL 内直接返回缓存值，不打 API 也不回退。"""
        universe_mod._universe_cache["CN"] = (
            time.monotonic(),
            ["600519.SH"],
            False,
        )

        async def boom(market: str) -> list[str]:
            raise AssertionError("正缓存命中不应发起请求")

        async def run():
            with mock.patch.object(
                universe_mod, "_fetch_market_symbols", side_effect=boom
            ):
                return await universe_mod._market_symbols("CN")

        self.assertEqual(asyncio.run(run()), ["600519.SH"])


if __name__ == "__main__":
    unittest.main()
