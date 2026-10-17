"""分钟触发参考线接线测试（H1 收口）。

覆盖点：
- 内置策略 ref 产出：MA/BOLL/趋势类价格穿越信号产出 entry_ref/exit_ref；
  非价格穿越类（量价齐升、超卖反转）保持 None（matcher 自动降级 VWAP）。
- build_minute_exit_reference 兜底接线：runner 在 exit_fill="signal_next_minute"
  且策略未产出 exit_ref 时（ma_golden_cross 死叉）反推 MA 触发线，
  使盘中触发走 minute_trigger 成交而非整体降级。

全部合成数据：runner 端到端用例用临时 QUANT_CACHE_DIR 种子 Parquet +
注入分钟K 帧，不依赖真实 data-api/网络/共享缓存目录。
"""
from __future__ import annotations

import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import polars as pl

from app.config import settings
from app.data import store
from app.matrix import MarketMatrix, enrich
from app.strategy.builtin import (
    boll_breakout,
    ma_golden_cross,
    oversold_reversal,
    volume_price_surge,
)

SYM = "AAPL"
D0 = date(2026, 1, 5)  # 周一


def _dates(n: int) -> list[date]:
    """连续自然日日期轴（合成数据不区分交易日，与既有测试口径一致）。"""
    return [D0 + timedelta(days=i) for i in range(n)]


def _enriched(closes: list[float]):
    """单列合成市场矩阵 → EnrichedMatrix（等成交量，量比恒 1）。"""
    n = len(closes)
    close = np.array(closes, dtype=np.float64).reshape(n, 1)
    return enrich(
        MarketMatrix(
            dates=_dates(n),
            symbols=[SYM],
            open=close.copy(),
            high=close.copy(),
            low=close.copy(),
            close=close,
            volume=np.full((n, 1), 1e6),
            amount=close * 1e6,
        )
    )


def _ref_at(ref: np.ndarray, sig: np.ndarray, j: int = 0) -> np.ndarray:
    """信号日（第 j 列）的参考线取值。"""
    return ref[sig[:, j], j]


class BuiltinRefsTest(unittest.TestCase):
    """内置策略 entry_ref/exit_ref 产出约定。"""

    def test_ma_golden_cross_refs(self) -> None:
        # 20 天平盘 → 5 天反弹出金叉（i=20）→ 回落出死叉（i=35）→ 低位平盘
        closes = (
            [10.0] * 20
            + [10.3, 10.6, 10.9, 11.2, 11.5]
            + [11.3, 11.0, 10.7]
            + [10.6] * 17
        )
        sig = ma_golden_cross.compute(
            _enriched(closes), {"require_above_ma60": False, "vol_ratio_min": 0.0}
        )
        self.assertTrue(sig.entry[:, 0].any(), "合成序列应产生金叉信号")
        self.assertTrue(sig.exit[:, 0].any(), "合成序列应产生死叉信号（阴跌段）")
        # entry_ref = MA20 慢线：金叉参考价线，金叉日必有有效值
        self.assertIsNotNone(sig.entry_ref)
        self.assertTrue(np.all(np.isfinite(_ref_at(sig.entry_ref, sig.entry))))
        # 死叉无直接价格参考线：保持 None，由 runner 反推兜底接线
        self.assertIsNone(sig.exit_ref)

    def test_boll_breakout_refs(self) -> None:
        # 微波动 20 天 + 单日大涨 20%：突破上轨（昨日 close 10.1 <= 昨日上轨），
        # 必触发上穿信号
        closes = [10.0 + 0.01 * i for i in range(20)] + [12.0]
        sig = boll_breakout.compute(_enriched(closes), {})
        self.assertTrue(sig.entry[-1, 0], "单日大涨应触发布林上轨突破")
        # entry_ref = 布林上轨：突破日必有有效值且被收盘穿越
        self.assertIsNotNone(sig.entry_ref)
        refs = _ref_at(sig.entry_ref, sig.entry)
        self.assertTrue(np.all(np.isfinite(refs)))
        self.assertGreater(closes[-1], float(refs[-1]))
        # exit_ref = MA20：跌破 MA20 离场信号的价格穿越线
        self.assertIsNotNone(sig.exit_ref)

    def test_volume_price_surge_no_refs(self) -> None:
        # 非价格穿越类信号（量比/动量阈值）：无天然参考线，保持 None 走 VWAP 降级
        closes = [10.0 + 0.1 * i for i in range(30)]
        sig = volume_price_surge.compute(
            _enriched(closes), {"mom_min": 0.01, "vol_min": 0.5}
        )
        self.assertTrue(sig.entry[:, 0].any(), "合成序列应产生量价信号")
        self.assertIsNone(sig.entry_ref)
        self.assertIsNone(sig.exit_ref)

    def test_oversold_reversal_no_refs(self) -> None:
        # RSI 阈值类信号同样无价格参考线
        closes = [20.0 - 0.5 * i for i in range(30)] + [6.0]
        sig = oversold_reversal.compute(_enriched(closes), {"rsi_threshold": 35.0})
        self.assertIsNone(sig.entry_ref)
        self.assertIsNone(sig.exit_ref)


# 日线合成场景（45 天）：20 天平盘 → 5 天反弹出金叉（i=20，次日 i=21 开盘
# 10.3 买入）→ 3 天回落出死叉（i=35，ref 触发线 10.7，恰高于止损线 9.68 不
# 抢跑）→ 低位平盘至区间结束。signal_next_minute 在信号当日（i=35）盘中确认：
# 分钟K 破线后回升、收盘收回线上（收盘口径无信号）——展示盘中触发独立于
# 收盘信号语义。
_E2E_N = 45
_E2E_GOLDEN_DAY = 20
_E2E_ENTRY_DAY = 21
_E2E_ENTRY_PRICE = 10.3
# matcher 对 signal_next_minute 在信号当日盘中确认（sig_i == i，右移口径仅
# open_t+1 适用），分钟K 挂在死叉信号日当天。
_E2E_DEAD_DAY = 35
_E2E_TRIGGER_DAY = 35
_E2E_TRIGGER_REF = 10.7
_E2E_TRIGGER_PRICE = 10.55
_E2E_DAY_CLOSE = 10.68
_E2E_CLOSES = (
    [10.0] * 20  # 0..19 平盘
    + [10.3, 10.6, 10.9, 11.2, 11.5]  # 20..24 反弹（i=20 金叉）
    + [11.3, 11.0, 10.7]  # 25..27 见顶回落
    + [10.6] * 17  # 28..44 低位平盘（i=35 死叉，ref=10.7）
)
_E2E_OPENS = _E2E_CLOSES[-1:] + _E2E_CLOSES[:-1]  # open[t] = close[t-1]，首日随意
_E2E_OPENS = _E2E_OPENS[:_E2E_N]
# 触发日（i=36，i-1=35 为死叉信号日）的分钟K：首根即破线确认下穿，收盘回升。
_E2E_MINUTES_DAY39 = np.array(
    [
        [10.60, 10.65, 10.50, 10.55, 100.0, 1055.0],  # 收盘 10.55 < 10.7（首根视为在线上方，确认下穿）
        [10.55, 10.58, 10.54, 10.56, 100.0, 1056.0],  # 下一分钟开盘 10.55 → 触发成交价
        [10.56, 10.62, 10.56, 10.60, 100.0, 1060.0],
        [10.56, 10.70, 10.56, 10.68, 100.0, 1068.0],  # 收盘回升 10.68（收盘口径无信号）
    ]
)


def _seed_parquet() -> None:
    """往当前缓存目录写合成日K（store.save 语义：已排序去重）。"""
    rows = {
        "symbol": [SYM] * _E2E_N,
        "date": _dates(_E2E_N),
        "open": _E2E_OPENS,
        "high": [max(o, c) for o, c in zip(_E2E_OPENS, _E2E_CLOSES)],
        "low": [min(o, c) for o, c in zip(_E2E_OPENS, _E2E_CLOSES)],
        "close": _E2E_CLOSES,
        "volume": [1_000_000] * _E2E_N,
        "amount": [c * 1e6 for c in _E2E_CLOSES],
    }
    store.save(SYM, pl.DataFrame(rows))


def _minute_frames() -> dict[str, pl.DataFrame]:
    """触发日分钟K 帧（datetime + _MINUTE_COLS 列序，与 _build_minute_loader 约定一致）。"""
    day = _dates(_E2E_N)[_E2E_TRIGGER_DAY]
    return {
        SYM: pl.DataFrame(
            {
                "datetime": [f"{day.isoformat()}T09:{31 + i}:00" for i in range(4)],
                "open": _E2E_MINUTES_DAY39[:, 0],
                "high": _E2E_MINUTES_DAY39[:, 1],
                "low": _E2E_MINUTES_DAY39[:, 2],
                "close": _E2E_MINUTES_DAY39[:, 3],
                "volume": _E2E_MINUTES_DAY39[:, 4],
                "amount": _E2E_MINUTES_DAY39[:, 5],
            }
        ).with_columns(pl.col("datetime").str.to_datetime())
    }


class RunnerMinuteTriggerWiringTest(unittest.TestCase):
    """runner 端到端：ma_golden_cross + signal_next_minute 走通盘中触发接线。"""

    def test_minute_trigger_via_runner_wiring(self) -> None:
        import inspect

        import app.runner as runner_mod
        from app.engine import MatcherConfig
        from app.runner import run_backtest
        from app.strategy import StrategyRegistry
        from app.strategy import loader as strategy_loader

        # 静态确认接线点存在（orphan 函数已接入信号管线）
        self.assertIn("build_minute_exit_reference", inspect.getsource(runner_mod))

        old_cache = settings.QUANT_CACHE_DIR
        with tempfile.TemporaryDirectory() as tmp:
            settings.QUANT_CACHE_DIR = tmp
            try:
                _seed_parquet()
                registry = StrategyRegistry(
                    {"builtin": Path(strategy_loader.__file__).parent / "builtin"}
                )
                result = run_backtest(
                    [SYM],
                    "ma_golden_cross",
                    _dates(_E2E_N)[0],
                    _dates(_E2E_N)[-1],
                    params={"require_above_ma60": False, "vol_ratio_min": 0.0},
                    config=MatcherConfig(exit_fill="signal_next_minute"),
                    registry=registry,
                    minute_bars=_minute_frames(),
                )
            finally:
                settings.QUANT_CACHE_DIR = old_cache

        trades = result["trades"]
        self.assertTrue(trades, "合成序列应产生至少一笔完整交易")
        # 分钟触发接线生效：至少一笔 signal 卖出走了 minute_trigger（而非降级日K）
        triggered = [t for t in trades if t["exit_fill_mode"] == "minute_trigger"]
        self.assertTrue(
            triggered,
            f"signal_next_minute 下应有 minute_trigger 成交，实际：{trades}",
        )
        t = triggered[0]
        self.assertEqual(t["exit_reason"], "signal")
        self.assertEqual(
            t["exit_date"], _dates(_E2E_N)[_E2E_TRIGGER_DAY].isoformat()
        )
        self.assertAlmostEqual(
            t["exit_price"], _E2E_TRIGGER_PRICE, places=9
        )  # 确认点下一分钟开盘
        # 该笔 exit_price 为反推触发线的盘中确认价，而非当日收盘（收盘口径无信号）
        self.assertNotAlmostEqual(t["exit_price"], _E2E_DAY_CLOSE, places=9)


if __name__ == "__main__":
    unittest.main()
