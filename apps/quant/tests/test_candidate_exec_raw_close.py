"""candidate_exec.simulate_independent 一字板判定基准价回归测试（缺陷 1）。

缺陷：one_price_limit 用复权 close 算涨跌停基准，与 matcher.blocked_by_limit
同源失真——前复权矩阵在除权日前整体被静态比例缩放，涨跌停基准偏离真实市价。

修复：simulate_independent 新增可选参数 raw_close（原始价 close 矩阵），
one_price_limit 的涨跌停基准取原始价；None 时回退旧行为（向后兼容）。

合成数据 + 本地复权（engine.adjust.forward_adjust + polars 因子表），
不依赖真实 data-api/网络；宿主机缺 polars 时整组显式跳过。
"""
from __future__ import annotations

import unittest
from datetime import date, timedelta

import numpy as np

try:
    import polars as pl

    from app.engine.adjust import forward_adjust
    from app.engine.candidate_exec import simulate_independent
    from app.engine.matcher import MatcherConfig
    from app.matrix import MarketMatrix

    _DEPS_OK = True
except ImportError as e:  # 宿主机缺依赖（polars 等）时整组跳过，不假装通过
    _DEPS_OK = False
    _IMPORT_ERROR = e

D0 = date(2026, 1, 5)
SYM = "600519.SH"  # CN 主板标的（±10% 档）


def _dates(n: int) -> list[date]:
    return [D0 + timedelta(days=i) for i in range(n)]


def _signals(n: int, fire_days: list[int]) -> np.ndarray:
    sig = np.zeros(n, dtype=bool)
    for i in fire_days:
        sig[i] = True
    return sig


def _matrix(prices: list[float], symbol: str = SYM) -> "MarketMatrix":
    """单列一字矩阵（OHLC 同价；原始价口径），volume>0 以免被判停牌。"""
    n = len(prices)
    p = np.array(prices, dtype=np.float64).reshape(n, 1)
    return MarketMatrix(
        dates=_dates(n),
        symbols=[symbol],
        open=p.copy(),
        high=p.copy(),
        low=p.copy(),
        close=p,
        volume=np.full((n, 1), 1e6),
        amount=p * 1e6,
    )


def _raw_matrix() -> "MarketMatrix":
    """除权场景原始价矩阵（下标 i）：
    i=0：收盘 19.90（除权前，factor=1.0）
    i=1：除权日，收盘 9.95（10 送 10，factor 1.0→2.0，价格腰斩；
         真实市场除权日正常交易，非一字跌停——跌停价 17.91 差得远）
    i=2：除权次日，收盘 10.945 = 9.95 × 1.10（原始价恰好顶格涨停）
    """
    return _matrix([19.90, 9.95, 10.945])


def _adjusted_matrix() -> "MarketMatrix":
    """本地前复权：除权因子在 i=0（首个交易日）生效，i=1 起跳变到 2.0，
    末日因子 2.0 为基准——i=0 复权价 19.90×1/2=9.95，i=1/i=2 = 原始价。"""
    adjusted, _ = forward_adjust(
        _raw_matrix(),
        # 首因子 1.0 落在 i=0（向历史延伸口径下 i=0 之前的日子也取 1.0），
        # i=1 起累计因子 2.0 —— 与 test_matcher_limit_price 的场景对齐。
        {SYM: pl.DataFrame(
            {"date": [_dates(3)[0], _dates(3)[1]], "ex_factor": [1.0, 2.0]}
        )},
    )
    return adjusted


@unittest.skipUnless(_DEPS_OK, f"缺运行依赖（如 polars），在 devcontainer/容器内跑：{_IMPORT_ERROR if not _DEPS_OK else ''}")
class CandidateExecRawCloseTest(unittest.TestCase):
    """缺陷 1 修复：one_price_limit 用原始价判定，跨除权日不再失真。"""

    def test_scenario_premise(self) -> None:
        """前置断言：锁定场景——i=0 复权价被缩放为 9.95（原始 19.90），
        原始价 i=1→i=2 涨幅恰为 10%（顶格涨停）。"""
        adjusted = _adjusted_matrix()
        raw = _raw_matrix()
        self.assertAlmostEqual(adjusted.close[0, 0], 9.95, places=9)
        self.assertAlmostEqual(raw.close[2, 0] / raw.close[1, 0] - 1.0, 0.10, places=9)

    def test_ex_div_day_not_misjudged_as_limit_up(self) -> None:
        """核心断言（涨停方向失真面）：i=0 收盘信号 → i=1 除权日开盘买入。

        原始价口径：prev_close=19.90，涨停价 21.89，当日收盘 9.95 远未涨停
        → 不拦。修复后按真实市价判定，除权日价格腰斩属正常除权。
        """
        r = simulate_independent(
            _adjusted_matrix(),
            entries={SYM: _signals(3, [0])},
            exits={SYM: _signals(3, [])},
            config=MatcherConfig(),
            raw_close=_raw_matrix().close,
        )
        self.assertEqual(len(r.trades), 1)
        self.assertEqual(r.trades[0].exit_reason, "end")
        self.assertEqual(r.trades[0].entry_date, _dates(3)[1])
        self.assertIsNone(r.execution_stats.get("buy_limit_up"))
        self.assertIsNone(r.execution_stats.get("buy_suspended"))

    def test_limit_up_blocked_with_raw_close(self) -> None:
        """raw_close 下除权次日（i=2）原始价顶格涨停 → 一字涨停拒买。

        i=1 收盘信号 → i=2 开盘买入尝试：prev_close=9.95（真实市价），
        涨停价 10.945 顶格 → buy_limit_up，零成交。
        """
        r = simulate_independent(
            _adjusted_matrix(),
            entries={SYM: _signals(3, [1])},
            exits={SYM: _signals(3, [])},
            config=MatcherConfig(),
            raw_close=_raw_matrix().close,
        )
        self.assertEqual(r.execution_stats.get("buy_limit_up"), 1)
        self.assertEqual(len(r.trades), 0)

    def test_backward_compat_fallback_without_raw_close(self) -> None:
        """向后兼容：raw_close 缺省时回退用 matrix.close 判定；
        传入本就是原始矩阵（未复权）时仍能拦下顶格涨停。"""
        r = simulate_independent(
            _raw_matrix(),
            entries={SYM: _signals(3, [1])},
            exits={SYM: _signals(3, [])},
            config=MatcherConfig(),
        )
        self.assertEqual(r.execution_stats.get("buy_limit_up"), 1)
        self.assertEqual(len(r.trades), 0)


if __name__ == "__main__":
    unittest.main()
