"""停牌股尾部空洞水位标记（build_async 不再重复回源）测试。

覆盖场景（对应 P1 缺陷：长期停牌/退市股尾部天然无数据，补拉返回空不落缓存，
每次回测重复回源且永不收敛）：
1. 连续两次 build_async 对同一停牌标的只回源一次（第二次水位命中跳过）。
2. 水位区间外的请求正常补拉并推进水位（last_checked_date < end 不豁免）。
3. 补拉到数据时清除水位标记（数据本身即覆盖证明）。
4. 水位文件损坏按未检查处理，正常补拉。
"""
from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from datetime import date, timedelta
from unittest import mock

try:
    import polars as pl

    from app.config import settings
    from app.data import store
    from app.matrix import build_async
    from app.matrix.market import _checked_file

    _DEPS_OK = True
except ImportError as e:  # 宿主机缺依赖（polars 等）时整组跳过，不假装通过
    _DEPS_OK = False
    _IMPORT_ERROR = e

SYM = "HALTED"
_D0 = date(2026, 1, 5)


def _bars(symbol: str, d0: date, closes: list[float]) -> list[dict]:
    """合成 /api/bars 响应行（fetch_bars 的 mock 返回）。"""
    return [
        {"symbol": symbol, "date": (d0 + timedelta(days=i)).isoformat(),
         "open": c, "high": c, "low": c, "close": c,
         "volume": 1_000_000, "amount": c * 1e6}
        for i, c in enumerate(closes)
    ]


@unittest.skipUnless(_DEPS_OK, f"缺运行依赖（如 polars），在 devcontainer/容器内跑：{_IMPORT_ERROR if not _DEPS_OK else ''}")
class StalledPrefetchCase(unittest.TestCase):
    """每个用例独立临时缓存目录（settings.QUANT_CACHE_DIR 换绑后还原）。"""

    def setUp(self) -> None:
        self._old_cache = settings.QUANT_CACHE_DIR
        self._tmp = tempfile.TemporaryDirectory()
        settings.QUANT_CACHE_DIR = self._tmp.name

    def tearDown(self) -> None:
        settings.QUANT_CACHE_DIR = self._old_cache
        self._tmp.cleanup()

    def test_repeated_build_fetches_only_once(self) -> None:
        """核心回归：mock fetch_bars 返回空，连续两次 build_async 只回源一次。"""
        start, end = _D0, _D0 + timedelta(days=9)
        fake = mock.AsyncMock(return_value=[])
        with mock.patch("app.data.client.fetch_bars", new=fake):
            m1 = asyncio.run(build_async([SYM], start, end))
            self.assertTrue(_checked_file(SYM).exists())
            m2 = asyncio.run(build_async([SYM], start, end))
        fake.assert_awaited_once()
        # 两次都正常降级返回（停牌标的无交易日轴，矩阵行为不变）
        self.assertEqual(m1.symbols, [SYM])
        self.assertEqual(m2.symbols, [SYM])
        self.assertEqual(m1.shape[0], 0)
        self.assertEqual(m2.shape[0], 0)
        # 缓存仍未落数据（无数据可写），靠水位标记收敛
        self.assertEqual(store.load(SYM).height, 0)

    def test_marker_progresses_when_end_moves_forward(self) -> None:
        """水位 last_checked_date < 请求 end：正常补拉，补拉后水位推进到新 end。"""
        start = _D0
        end1 = _D0 + timedelta(days=9)
        end2 = _D0 + timedelta(days=19)
        fake = mock.AsyncMock(return_value=[])
        with mock.patch("app.data.client.fetch_bars", new=fake):
            asyncio.run(build_async([SYM], start, end1))
            m1 = json.loads(_checked_file(SYM).read_text(encoding="utf-8"))
            self.assertEqual(m1["last_checked_date"], end1.isoformat())
            # 请求 end 超出水位：补拉第二次，水位推进到 end2
            asyncio.run(build_async([SYM], start, end2))
        self.assertEqual(fake.await_count, 2)
        m2 = json.loads(_checked_file(SYM).read_text(encoding="utf-8"))
        self.assertEqual(m2["last_checked_date"], end2.isoformat())
        self.assertEqual(m2["requested_start"], start.isoformat())

    def test_marker_cleared_when_data_arrives(self) -> None:
        """复牌：先空补拉落水位，后补拉到数据时删除水位标记并落缓存。"""
        start, end = _D0, _D0 + timedelta(days=9)
        with mock.patch(
            "app.data.client.fetch_bars", new=mock.AsyncMock(return_value=[])
        ):
            asyncio.run(build_async([SYM], start, end))
        self.assertTrue(_checked_file(SYM).exists())
        # 手填过期水位（end 之前），模拟复牌后请求更大区间
        _checked_file(SYM).write_text(json.dumps({
            "last_checked_date": (end - timedelta(days=5)).isoformat(),
            "requested_start": start.isoformat(),
            "requested_end": (end - timedelta(days=5)).isoformat(),
        }), encoding="utf-8")
        fake = mock.AsyncMock(return_value=_bars(SYM, start, [10.0] * 10))
        with mock.patch("app.data.client.fetch_bars", new=fake):
            matrix = asyncio.run(build_async([SYM], start, end))
        fake.assert_awaited_once()
        self.assertFalse(_checked_file(SYM).exists())
        self.assertEqual(store.load(SYM).height, 10)
        j = matrix.symbols.index(SYM)
        self.assertFalse(any(v != v for v in matrix.close[:, j]))

    def test_corrupt_marker_refetches(self) -> None:
        """水位文件损坏：按未检查处理正常补拉，并重建标记。"""
        start, end = _D0, _D0 + timedelta(days=4)
        path = _checked_file(SYM)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not-json", encoding="utf-8")
        fake = mock.AsyncMock(return_value=[])
        with mock.patch("app.data.client.fetch_bars", new=fake):
            asyncio.run(build_async([SYM], start, end))
        fake.assert_awaited_once()
        m = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(m["last_checked_date"], end.isoformat())

    def test_partial_cache_with_marker_still_fetches(self) -> None:
        """缓存有数据但盖不住尾部、水位也已过期：不豁免，正常补拉。"""
        start, end = _D0, _D0 + timedelta(days=9)
        # 缓存只到 _D0+4（尾部停牌空洞），水位只确认到 _D0+6 < end
        closes = [10.0] * 5
        store.save(SYM, pl.DataFrame({
            "symbol": [SYM] * 5,
            "date": [start + timedelta(days=i) for i in range(5)],
            "open": closes, "high": closes, "low": closes, "close": closes,
            "volume": [1_000_000] * 5,
            "amount": [c * 1e6 for c in closes],
        }))
        path = _checked_file(SYM)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "last_checked_date": (start + timedelta(days=6)).isoformat(),
            "requested_start": start.isoformat(),
            "requested_end": (start + timedelta(days=6)).isoformat(),
        }), encoding="utf-8")
        fake = mock.AsyncMock(return_value=[])
        with mock.patch("app.data.client.fetch_bars", new=fake):
            asyncio.run(build_async([SYM], start, end))
        fake.assert_awaited_once()
        # 补拉仍空：水位推进到 end（尾部空洞确认收敛）
        m = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(m["last_checked_date"], end.isoformat())


if __name__ == "__main__":
    unittest.main()
