"""涨跌停判定基准价回归测试（P1：跨除权日复权价失真修复）。

缺陷：matcher.blocked_by_limit 用前复权 close 算涨跌停价，前复权矩阵在除权
日前整体被静态比例缩放（adjust.py 口径：复权价[t] = 原始价[t] × factor[t] /
factor[末]），prev_close 落在除权日之前时判定基准偏离真实市价——真实市场
中未涨停的正常开盘日被误拦（或反向场景下一字涨停漏判）。

修复：simulate 新增可选参数 raw_close（原始价 close 矩阵），仅供涨跌停判定；
信号、成交价、收益率计算仍用复权矩阵。raw_close 为 None 时回退旧行为。

合成数据 + 本地复权（engine.adjust.forward_adjust + polars 因子表），
不依赖真实 data-api/网络；工具函数风格对齐 tests/test_matcher.py。
"""
from __future__ import annotations

import unittest
from datetime import date, timedelta

import numpy as np

try:
    import polars as pl

    from app.engine.adjust import forward_adjust
    from app.engine.matcher import MatcherConfig, simulate
    from app.matrix import MarketMatrix

    _DEPS_OK = True
except ImportError as e:  # 宿主机缺依赖（polars 等）时整组跳过，不假装通过
    _DEPS_OK = False
    _IMPORT_ERROR = e

D0 = date(2026, 1, 5)
SYM = "600519.SH"  # CN 主板标的（±10% 档），触发涨跌停判定


def _dates(n: int) -> list[date]:
    return [D0 + timedelta(days=i) for i in range(n)]


def _signals(n: int, fire_days: list[int]) -> np.ndarray:
    """收盘信号 bool 数组（fire_days 为信号产生的日期下标）。"""
    sig = np.zeros(n, dtype=bool)
    for i in fire_days:
        sig[i] = True
    return sig


def _matrix(opens: list[float], closes: list[float], symbol: str = SYM) -> MarketMatrix:
    """单列合成市场矩阵（OHLC 同价；原始价口径）。"""
    n = len(closes)
    close = np.array(closes, dtype=np.float64).reshape(n, 1)
    openp = np.array(opens, dtype=np.float64).reshape(n, 1)
    return MarketMatrix(
        dates=_dates(n),
        symbols=[symbol],
        open=openp,
        high=close.copy(),
        low=close.copy(),
        close=close,
        volume=np.full((n, 1), 1e6),
        amount=close * 1e6,
    )


def _raw_matrix() -> MarketMatrix:
    """除权场景原始价矩阵（下标 i）：
    i=0：收盘 19.90（除权前，factor=2.0 未生效）
    i=1：除权日，收盘 9.95（10 送 10，factor 1.0→2.0，价格腰斩；
         真实市场除权日正常交易，非一字板）
    i=2：除权次日，收盘 10.945 = 9.95 × 1.10（原始价恰好顶格涨停）
    """
    return _matrix(opens=[19.90, 9.95, 10.945], closes=[19.90, 9.95, 10.945])


def _adjusted_matrix() -> MarketMatrix:
    """本地前复权：i=0 复权价 19.90×1/2=9.95，i=1/i=2 复权价 = 原始价。"""
    adjusted, _ = forward_adjust(
        _raw_matrix(),
        # 除权因子表：i=1（除权日）起累计因子由 1.0 跳变到 2.0
        {SYM: pl.DataFrame({"date": [_dates(3)[1]], "ex_factor": [2.0]})},
    )
    return adjusted


def _run(matrix: MarketMatrix, entry_fire: list[int], raw_close: np.ndarray | None):
    """跑撮合，返回 SimResult。"""
    return simulate(
        matrix,
        entries={SYM: _signals(3, entry_fire)},
        exits={SYM: _signals(3, [])},
        config=MatcherConfig(),
        raw_close=raw_close,
    )


@unittest.skipUnless(_DEPS_OK, f"缺运行依赖（如 polars），在 devcontainer/容器内跑：{_IMPORT_ERROR if not _DEPS_OK else ''}")
class LimitPriceRawBasisTest(unittest.TestCase):
    """P1 修复：blocked_by_limit 用原始价判定，跨除权日不再失真。"""

    def test_scenario_premise(self) -> None:
        """前置断言：锁定场景——i=0 复权价被缩放为 9.95（原始 19.90），
        原始价 i=1→i=2 涨幅恰为 10%（顶格涨停）。"""
        adjusted = _adjusted_matrix()
        raw = _raw_matrix()
        self.assertAlmostEqual(adjusted.close[0, 0], 9.95, places=9)
        self.assertAlmostEqual(raw.close[2, 0] / raw.close[1, 0] - 1.0, 0.10, places=9)

    def test_limit_up_blocked_with_raw_close(self) -> None:
        """核心断言：除权次日原始价顶格涨停（9.95→10.945）→ 买入被拦、零成交。

        i=1 收盘信号 → i=2 开盘买入尝试；raw_close 下 prev_close=9.95（真实市价），
        涨停价 10.945 顶格 → blocked_buy_limit。
        """
        r = _run(_adjusted_matrix(), [1], _raw_matrix().close)
        self.assertEqual(r.execution_stats.get("blocked_buy_limit", 0), 1)
        self.assertEqual(len(r.trades), 0)

    def test_no_false_block_across_ex_div_boundary(self) -> None:
        """prev_close 跨除权日的误拦场景（本 P1 的直接失真面）：
        i=0 收盘信号 → i=1（除权日）开盘买入尝试。

        原始价口径：prev_close=19.90，涨停价 21.89，当日收盘 9.95 远未涨停
        → 不拦（除权日价格腰斩属正常除权，不是跌停/一字板）。
        修复前（复权 close 口径）：prev_close 被缩放为 9.95，虽本例结论同为
        不拦，但判定基准偏离真实市价；本用例固化修复后按真实市价判定的语义。
        """
        r = _run(_adjusted_matrix(), [0], _raw_matrix().close)
        self.assertEqual(r.execution_stats.get("blocked_buy_limit", 0), 0)
        self.assertEqual(len(r.trades), 1)  # i=1 开盘买入，期末 end 平仓
        self.assertEqual(r.trades[0].exit_reason, "end")

    def test_backward_compat_fallback_without_raw_close(self) -> None:
        """向后兼容：raw_close 缺省时回退用 matrix.close 判定；
        传入本就是原始矩阵（未复权）时仍能拦下顶格涨停。"""
        r = _run(_raw_matrix(), [1], None)
        self.assertEqual(r.execution_stats.get("blocked_buy_limit", 0), 1)
        self.assertEqual(len(r.trades), 0)


if __name__ == "__main__":
    unittest.main()
