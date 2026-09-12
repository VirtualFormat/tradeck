"""universe 解析 + screen(symbols=None) 集成路径的回归测试。

覆盖点：
- resolve_universe：显式 symbols 优先 / 各档位展开 / 未知档位报错
- screen(symbols=None)：走 resolve_universe 展开（tracked 全集），不触网
  （mock build 返回合成矩阵 + 桩 registry 返回合成信号）。
"""
from __future__ import annotations

import unittest
from datetime import date, timedelta
from unittest import mock

import numpy as np

from app.jobs import DEFAULT_SIGNAL_UNIVERSE
from app.matrix import MarketMatrix
from app.screener.executor import screen
from app.universe import resolve_universe

_CN_SUFFIXES = (".SH", ".SS", ".SZ", ".BJ")
_D0 = date(2026, 1, 5)


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
    def test_explicit_symbols_returned_as_is(self):
        symbols = ["AAPL", "600519.SH"]
        # 显式 symbols 优先：即使带 universe 参数也忽略
        self.assertEqual(resolve_universe(symbols, None), symbols)
        self.assertEqual(resolve_universe(symbols, "cn"), symbols)

    def test_default_tier_returns_full_tracked(self):
        got = resolve_universe(None, None)
        self.assertEqual(got, DEFAULT_SIGNAL_UNIVERSE)
        self.assertIsNot(got, DEFAULT_SIGNAL_UNIVERSE)  # 副本，防外部改坏源列表

    def test_cn_tier_only_cn_suffixes(self):
        got = resolve_universe(None, "cn")
        self.assertTrue(got)
        self.assertTrue(all(s.endswith(_CN_SUFFIXES) for s in got))

    def test_hk_tier_only_hk_suffix(self):
        got = resolve_universe(None, "hk")
        self.assertTrue(got)
        self.assertTrue(all(s.endswith(".HK") for s in got))

    def test_us_tier_has_no_suffix(self):
        got = resolve_universe(None, "us")
        self.assertTrue(got)
        self.assertTrue(
            all(not s.endswith(_CN_SUFFIXES) and not s.endswith(".HK") for s in got)
        )

    def test_all_tier_equals_tracked(self):
        self.assertEqual(resolve_universe(None, "all"), DEFAULT_SIGNAL_UNIVERSE)

    def test_unknown_tier_raises(self):
        with self.assertRaises(ValueError):
            resolve_universe(None, "unknown")


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
