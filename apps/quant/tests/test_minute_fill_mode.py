"""minute_fill.resolve_minute_fill_with_mode 单元测试（缺陷 4）。

缺陷 4：matcher._minute_crossed 与 resolve_minute_fill 的穿越判定是重复
实现，未来易分叉。修复：minute_fill 新增 resolve_minute_fill_with_mode，
成交模式（minute_ref / minute_vwap / minute_close）由返回分支带出；
resolve_minute_fill 改为薄包装（只取价格），旧签名不变（minute_replay
等既有调用方不受影响）。

纯 numpy 合成分钟K，不依赖 data-api/网络；宿主机缺 polars 时显式跳过
（本模块只走 numpy，但 app.engine 包 __init__ 链式导入 polars）。
"""
from __future__ import annotations

import unittest

import numpy as np

try:
    from app.engine.minute_fill import resolve_minute_fill, resolve_minute_fill_with_mode

    _DEPS_OK = True
except ImportError as e:  # 宿主机缺依赖（polars 等）时整组跳过，不假装通过
    _DEPS_OK = False
    _IMPORT_ERROR = e


def _minutes(open_: float, high: float, low: float, close: float,
             vol: float = 100.0, amt: float | None = None) -> np.ndarray:
    """单根分钟K 行（调用方可多行 vstack）；amt 缺省 = close x vol。"""
    return np.array([[open_, high, low, close, vol, amt if amt is not None else close * vol]])


@unittest.skipUnless(_DEPS_OK, f"缺运行依赖（如 polars），在 devcontainer/容器内跑：{_IMPORT_ERROR if not _DEPS_OK else ''}")
class ResolveMinuteFillWithModeTest(unittest.TestCase):
    """带模式标注变体：模式由返回分支带出，与价格同源。"""

    def test_missing_minutes_returns_none_none(self) -> None:
        self.assertEqual(resolve_minute_fill_with_mode(None, 10.0, "buy"), (None, None))
        self.assertEqual(
            resolve_minute_fill_with_mode(np.empty((0, 6)), 10.0, "buy"),
            (None, None),
        )

    def test_buy_open_already_crossed_mode_ref(self) -> None:
        # 开盘 10.5 >= 参考线 10.0 → 开盘价成交，minute_ref
        price, mode = resolve_minute_fill_with_mode(
            _minutes(10.5, 10.6, 10.4, 10.5), 10.0, "buy"
        )
        self.assertEqual(mode, "minute_ref")
        self.assertAlmostEqual(price, 10.5, places=12)

    def test_buy_intraday_touch_mode_ref_at_ref_price(self) -> None:
        # 开盘 9.8 < 10.0，高点 10.2 >= 10.0 → 按参考线成交，minute_ref
        price, mode = resolve_minute_fill_with_mode(
            _minutes(9.8, 10.2, 9.7, 10.1), 10.0, "buy"
        )
        self.assertEqual(mode, "minute_ref")
        self.assertAlmostEqual(price, 10.0, places=12)

    def test_buy_not_crossed_mode_close(self) -> None:
        # 全天高点 9.9 < 参考线 10.0 → 信号确认收盘价，minute_close
        price, mode = resolve_minute_fill_with_mode(
            _minutes(9.8, 9.9, 9.7, 9.85), 10.0, "buy"
        )
        self.assertEqual(mode, "minute_close")
        self.assertAlmostEqual(price, 9.85, places=12)

    def test_sell_symmetric_breakdown(self) -> None:
        # 卖出对称：开盘 9.5 <= 参考线 10.0 → 开盘价成交，minute_ref
        price, mode = resolve_minute_fill_with_mode(
            _minutes(9.5, 9.6, 9.4, 9.5), 10.0, "sell"
        )
        self.assertEqual(mode, "minute_ref")
        self.assertAlmostEqual(price, 9.5, places=12)
        # 开盘 10.5 > 10.0，低点 9.9 <= 10.0 → 参考线成交，minute_ref
        price, mode = resolve_minute_fill_with_mode(
            _minutes(10.5, 10.6, 9.9, 10.0), 10.0, "sell"
        )
        self.assertEqual(mode, "minute_ref")
        self.assertAlmostEqual(price, 10.0, places=12)
        # 全天低点 10.1 > 10.0 → 信号确认收盘价，minute_close
        price, mode = resolve_minute_fill_with_mode(
            _minutes(10.5, 10.6, 10.1, 10.4), 10.0, "sell"
        )
        self.assertEqual(mode, "minute_close")
        self.assertAlmostEqual(price, 10.4, places=12)

    def test_no_ref_uses_vwap_mode(self) -> None:
        # 无参考线 → VWAP = sum(amount)/sum(volume)，minute_vwap
        marr = np.vstack([
            _minutes(10.0, 10.0, 10.0, 10.0, vol=100.0, amt=1000.0),
            _minutes(11.0, 11.0, 11.0, 11.0, vol=300.0, amt=3300.0),
        ])
        price, mode = resolve_minute_fill_with_mode(marr, None, "buy")
        self.assertEqual(mode, "minute_vwap")
        self.assertAlmostEqual(price, 4300.0 / 400.0, places=12)

    def test_wrapper_resolve_minute_fill_price_only(self) -> None:
        """旧签名包装：只取价格，与 with_mode 的价格一致（兼容性锁定）。"""
        marr = _minutes(9.8, 10.2, 9.7, 10.1)
        self.assertAlmostEqual(
            resolve_minute_fill(marr, 10.0, "buy"),
            resolve_minute_fill_with_mode(marr, 10.0, "buy")[0],
            places=12,
        )
        self.assertIsNone(resolve_minute_fill(None, 10.0, "buy"))


if __name__ == "__main__":
    unittest.main()
