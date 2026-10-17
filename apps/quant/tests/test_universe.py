"""universe 解析 + screen(symbols=None) 集成路径的回归测试。

覆盖点：
- resolve_universe：显式 symbols 优先 / 各档位展开 / 未知档位报错；
  cn 档位从 data-api /api/universe 拉全市场清单（mock get_json），
  源不可达时回退 tracked 子集
- screen(symbols=None)：走 resolve_universe 展开（tracked 全集），不触网
  （mock build 返回合成矩阵 + 桩 registry 返回合成信号）。
"""
from __future__ import annotations

import asyncio
import unittest
from datetime import date, timedelta
from unittest import mock

import numpy as np

import app.universe as universe_mod
from app.jobs import DEFAULT_SIGNAL_UNIVERSE
from app.matrix import MarketMatrix
from app.screener.executor import screen
from app.universe import resolve_universe

_CN_SUFFIXES = (".SH", ".SS", ".SZ", ".BJ")
_D0 = date(2026, 1, 5)


def _resolve(symbols, tier):
    """同步包装 async resolve_universe（unittest 不引 IsolatedAsyncioTestCase）。"""
    return asyncio.run(resolve_universe(symbols, tier))


def _fake_market_symbols(market: str) -> dict:
    """模拟 /api/universe 响应：只造 CN 全市场，美港返回空（走回退）。"""
    if market == "CN":
        return {"symbols": ["600519.SH", "000001.SZ", "300750.SZ"], "count": 3}
    return {"symbols": [], "count": 0}


async def _async_return(value):
    return value


def _fake_matrix(symbols: list[str], n: int = 70) -> MarketMatrix:
    """n 个交易日 × len(symbols) 只标的的合成矩阵（价格恒正，量额充足）。"""
    dates = [_D0 + timedelta(days=i) for i in range(n)]
    shape = (n, len(symbols))
    close = np.full(shape, 10.0)
    return MarketMatrix(
        dates=dates,
        symbols=list(symbols),
        open=close.copy(),
        high=close.copy(),
        low=close.copy(),
        close=close,
        volume=np.full(shape, 1e6),
        amount=np.full(shape, 1e7),
    )


class _FakeStrat:
    """桩策略定义：只提供 executor 用到的 meta 字段。"""

    def __init__(self, strategy_id: str):
        self.meta = {"id": strategy_id, "limit": 100, "descending": True}


class _FakeSignals:
    """桩信号：全 False entry（无人入选即可，只验证不报错）。"""

    def __init__(self, shape: tuple[int, int]):
        self.entry = np.zeros(shape, dtype=bool)
        self.exit = np.zeros(shape, dtype=bool)
        self.score = np.full(shape, np.nan)


class _FakeRegistry:
    def __init__(self, strategy_id: str):
        self._sid = strategy_id

    def get(self, strategy_id: str):
        return _FakeStrat(strategy_id)

    def run(self, strategy_id: str, enriched, params):
        return _FakeSignals(enriched.base.close.shape)


class TestResolveUniverse(unittest.TestCase):
    def setUp(self):
        # 每个用例清空清单缓存，避免跨用例污染
        universe_mod._universe_cache.clear()

    def test_explicit_symbols_returned_as_is(self):
        symbols = ["AAPL", "600519.SH"]
        # 显式 symbols 优先：即使带 universe 参数也忽略
        self.assertEqual(_resolve(symbols, None), symbols)
        self.assertEqual(_resolve(symbols, "cn"), symbols)

    def test_default_tier_returns_full_tracked(self):
        """默认档位（None）= hs300 沪深300，走指数成分接口。"""
        with mock.patch.object(
            universe_mod, "_fetch_index_symbols", return_value=["600519.SH", "300750.SZ"]
        ) as fetch:
            got = _resolve(None, None)
        self.assertEqual(got, ["600519.SH", "300750.SZ"])
        # 默认档位应映射到沪深300 指数代码
        fetch.assert_called_once_with("000300.SH")

    def test_tracked_tier_returns_full_tracked(self):
        got = _resolve(None, "tracked")
        self.assertEqual(got, DEFAULT_SIGNAL_UNIVERSE)
        self.assertIsNot(got, DEFAULT_SIGNAL_UNIVERSE)  # 副本，防外部改坏源列表

    def test_hs300_tier_fetches_index_constituents(self):
        """hs300 档位：调 data-api /api/index/constituents 拉沪深300 成分。"""
        with mock.patch.object(
            universe_mod, "_fetch_index_symbols", return_value=["600519.SH", "000001.SZ"]
        ) as fetch:
            got = _resolve(None, "hs300")
        self.assertEqual(got, ["600519.SH", "000001.SZ"])
        fetch.assert_called_once_with("000300.SH")

    def test_csi500_tier_fetches_index_constituents(self):
        """csi500 档位：中证500 成分（index=000905.SH）。"""
        with mock.patch.object(
            universe_mod, "_fetch_index_symbols", return_value=["000905.SH-x"]
        ) as fetch:
            _resolve(None, "csi500")
        fetch.assert_called_once_with("000905.SH")

    def test_hs300_tier_fallback_to_tracked_cn_subset(self):
        """hs300 档位：成分接口不可达/为空时回退 tracked 的 cn 子集。"""
        with mock.patch.object(
            universe_mod, "_fetch_index_symbols", return_value=[]
        ):
            got = _resolve(None, "hs300")
        self.assertTrue(got)
        self.assertTrue(all(s.endswith(_CN_SUFFIXES) for s in got))

    def test_cn_tier_fetches_market_universe(self):
        """cn 档位：调 data-api /api/universe 拉全市场清单（含 TTL 缓存）。"""
        with mock.patch.object(
            universe_mod,
            "_fetch_market_symbols",
            side_effect=lambda m: _fake_market_symbols(m)["symbols"],
        ) as fetch:
            got = _resolve(None, "cn")
            self.assertEqual(got, ["600519.SH", "000001.SZ", "300750.SZ"])
            # 第二次命中缓存，不再调 data-api
            got2 = _resolve(None, "cn")
            self.assertEqual(got2, got)
            self.assertEqual(fetch.call_count, 1)

    def test_cn_tier_fallback_to_tracked_subset(self):
        """cn 档位：data-api 不可达/为空时回退 tracked 的 cn 子集。"""
        with mock.patch.object(
            universe_mod, "_fetch_market_symbols", return_value=[]
        ):
            got = _resolve(None, "cn")
        self.assertTrue(got)
        self.assertTrue(all(s.endswith(_CN_SUFFIXES) for s in got))

    def test_hk_tier_only_hk_suffix(self):
        got = _resolve(None, "hk")
        self.assertTrue(got)
        self.assertTrue(all(s.endswith(".HK") for s in got))

    def test_us_tier_has_no_suffix(self):
        got = _resolve(None, "us")
        self.assertTrue(got)
        self.assertTrue(
            all(not s.endswith(_CN_SUFFIXES) and not s.endswith(".HK") for s in got)
        )

    def test_all_tier_cn_market_plus_tracked_rest(self):
        """all 档位：cn 全市场 + tracked 的美港部分。"""
        with mock.patch.object(
            universe_mod,
            "_fetch_market_symbols",
            side_effect=lambda m: _fake_market_symbols(m)["symbols"],
        ):
            got = _resolve(None, "all")
        self.assertEqual(got[:3], ["600519.SH", "000001.SZ", "300750.SZ"])
        rest = got[3:]
        self.assertEqual(
            rest, [s for s in DEFAULT_SIGNAL_UNIVERSE if not s.endswith(_CN_SUFFIXES)]
        )

    def test_unknown_tier_raises(self):
        with self.assertRaises(ValueError):
            _resolve(None, "unknown")


class TestScreenWithUniverse(unittest.TestCase):
    def test_screen_symbols_none_runs_without_error(self):
        """symbols=None → 展开为 tracked 全集，走完整管线不报错（不触网）。"""
        seen: dict[str, list[str]] = {}

        def fake_build(symbols, start, end):
            seen["symbols"] = list(symbols)
            return _fake_matrix(symbols)

        with (
            mock.patch("app.screener.executor.build", side_effect=fake_build),
            mock.patch(
                "app.screener.executor.factors.load",
                side_effect=lambda s: None,  # 无因子 → 全部降级无复权
            ),
        ):
            result = screen(
                "test_strategy", symbols=None, registry=_FakeRegistry("test_strategy")
            )

        self.assertEqual(seen["symbols"], DEFAULT_SIGNAL_UNIVERSE)
        self.assertEqual(result.strategy_id, "test_strategy")
        self.assertEqual(result.total, 0)
        self.assertEqual(result.rows, [])
        # 无因子标的应全部列入 unadjusted 降级标注
        self.assertEqual(sorted(result.unadjusted), sorted(DEFAULT_SIGNAL_UNIVERSE))


if __name__ == "__main__":
    unittest.main()
