"""engine.limits 的回归测试（阶段 G2 精确涨跌停验收点固化）。

覆盖点（plans/TASKS-QUANT-BACKTEST.md G2 复核记录）：
- 北交所 ±30%（.BJ 后缀）。
- 科创板（688/689）2019-07-22 开板起 ±20%，此前 ±10%。
- 创业板（300/301）2020-08-24 注册制起 ±20%，此前 ±10%。
- 主板 ±10%；主板 ST 2026-07-06 新规前 ±5%，新规起 ±10%。
- 仅主板 ST 特判：创业板/科创板/北交所 ST 跟随板块档。
- is_risk_warning_name：名称大写含 "ST"（*ST 与普通 ST 同判定）。
- 降级语义：name 缺省（空串）按非 ST 分档，不臆造 ST 拦截。
"""
from __future__ import annotations

import unittest
from datetime import date, timedelta

from app.engine.limits import (
    CHINEXT_REGISTRATION_DATE,
    MAIN_BOARD_ST_LIMIT_CHANGE_DATE,
    STAR_BOARD_OPEN_DATE,
    is_risk_warning_name,
    limit_pct,
)


class LimitPctTest(unittest.TestCase):
    """分档边界值（生效日当天与前一天对照）。"""

    def test_beijing_board_always_30pct(self) -> None:
        self.assertAlmostEqual(limit_pct("830799.BJ", date(2024, 1, 4)), 0.30)
        self.assertAlmostEqual(limit_pct("430047.BJ", date(2026, 8, 3)), 0.30)

    def test_star_board_before_and_after_open(self) -> None:
        before = STAR_BOARD_OPEN_DATE - timedelta(days=1)
        on = STAR_BOARD_OPEN_DATE
        # 开板前无 688 标的上市，分档仅为语义完备（口径注释）
        self.assertAlmostEqual(limit_pct("688001.SH", before), 0.10)
        self.assertAlmostEqual(limit_pct("688001.SH", on), 0.20)
        self.assertAlmostEqual(limit_pct("689009.SH", on), 0.20)

    def test_chinext_before_and_after_registration(self) -> None:
        before = CHINEXT_REGISTRATION_DATE - timedelta(days=1)
        on = CHINEXT_REGISTRATION_DATE
        self.assertAlmostEqual(limit_pct("300001.SZ", before), 0.10)
        self.assertAlmostEqual(limit_pct("300001.SZ", on), 0.20)
        self.assertAlmostEqual(limit_pct("301001.SZ", date(2026, 1, 5)), 0.20)

    def test_main_board_10pct(self) -> None:
        self.assertAlmostEqual(limit_pct("600519.SH", date(2024, 1, 4)), 0.10)
        self.assertAlmostEqual(limit_pct("000001.SZ", date(2026, 1, 5)), 0.10)

    def test_main_board_st_5pct_before_rule_change(self) -> None:
        before = MAIN_BOARD_ST_LIMIT_CHANGE_DATE - timedelta(days=1)
        on = MAIN_BOARD_ST_LIMIT_CHANGE_DATE
        self.assertAlmostEqual(limit_pct("600519.SH", before, name="ST 茅台"), 0.05)
        self.assertAlmostEqual(limit_pct("000001.SZ", before, name="*ST 平安"), 0.05)
        # 新规生效日起主板 ST 回归 ±10%
        self.assertAlmostEqual(limit_pct("600519.SH", on, name="ST 茅台"), 0.10)

    def test_st_on_other_boards_follow_board_tier(self) -> None:
        # 创业板/科创板/北交所 ST 跟随板块档（参照 price_limit_pct 口径）
        self.assertAlmostEqual(
            limit_pct("300001.SZ", date(2026, 1, 5), name="ST 创板"), 0.20
        )
        self.assertAlmostEqual(
            limit_pct("688001.SH", date(2026, 1, 5), name="ST 科创"), 0.20
        )
        self.assertAlmostEqual(
            limit_pct("830799.BJ", date(2026, 1, 5), name="ST 北交"), 0.30
        )

    def test_empty_name_degrades_to_non_st(self) -> None:
        # 降级语义：无名称信息宁可按普通股口径，不臆造 ST 拦截
        self.assertAlmostEqual(limit_pct("600519.SH", date(2024, 1, 4), name=""), 0.10)
        self.assertAlmostEqual(limit_pct("600519.SH", date(2024, 1, 4)), 0.10)


class RiskWarningNameTest(unittest.TestCase):
    """is_risk_warning_name：名称大写含 ST（*ST 与普通 ST 同判定）。"""

    def test_st_variants(self) -> None:
        self.assertTrue(is_risk_warning_name("ST 茅台"))
        self.assertTrue(is_risk_warning_name("*ST 平安"))
        self.assertTrue(is_risk_warning_name("st 银行"))  # 小写也算（大写后判定）
        self.assertTrue(is_risk_warning_name("退 ST 股"))

    def test_non_st_names(self) -> None:
        self.assertFalse(is_risk_warning_name("贵州茅台"))
        self.assertFalse(is_risk_warning_name("东方财富"))

    def test_none_degrades(self) -> None:
        self.assertFalse(is_risk_warning_name(None))
        self.assertFalse(is_risk_warning_name(""))


if __name__ == "__main__":
    unittest.main()
