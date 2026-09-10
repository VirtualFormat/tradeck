"""A 股涨跌停分档规则（精确口径）。

ST 判定与板块分档口径照搬参照实现
tick-stock-panel backend/app/price_limits.py（price_limit_pct / is_risk_warning_name）：
- ST 判定：名称大写后含 "ST"（*ST 与普通 ST 同一函数判定，不区分）。
- 仅主板 ST 走 ±5%（2026-07-06 主板 ST 涨跌幅新规前）；创业板/科创板/北交所
  ST 一律跟随板块档（±20%/±30%），参照口径即如此。
日期分档为本模块在参照口径上叠加的历史口径：
- 科创板 2019-07-22 开板起 ±20%（此前无 688 标的上市，分档仅为语义完备）。
- 创业板 2020-08-24 注册制起 ±20%，此前 ±10%。

已知边界：上市首日无涨跌幅限制（主板首日 ±44%/±36%、科创/创业板首 5 日不设限
等）未处理——日K 撮合只能保守按常规档拦截，新上市初期可能误拦，属可接受偏差。
"""
from __future__ import annotations

from datetime import date

MAIN_BOARD_LIMIT = 0.10
LEGACY_MAIN_BOARD_ST_LIMIT = 0.05
GROWTH_BOARD_LIMIT = 0.20
BEIJING_BOARD_LIMIT = 0.30

# 科创板开板日（688 首批上市，开板即 ±20%）
STAR_BOARD_OPEN_DATE = date(2019, 7, 22)
# 创业板注册制首批上市日（此后 ±20%，此前 ±10%）
CHINEXT_REGISTRATION_DATE = date(2020, 8, 24)
# 主板 ST 涨跌幅由 ±5% 调整为 ±10% 的生效日（参照 price_limits.py 常数）
MAIN_BOARD_ST_LIMIT_CHANGE_DATE = date(2026, 7, 6)


def is_risk_warning_name(name: str | None) -> bool:
    """ST/*ST 判定（照搬参照 is_risk_warning_name：名称大写含 "ST"）。"""
    return "ST" in str(name or "").upper()


def limit_pct(symbol: str, trade_date: date, name: str = "") -> float:
    """标的在 trade_date 的涨跌停幅度（小数）。

    name 缺省（空串）时按非 ST 分档——降级语义：无名称信息宁可按普通股口径，
    不臆造 ST 拦截。
    """
    if symbol.endswith(".BJ"):
        return BEIJING_BOARD_LIMIT
    code = symbol.split(".")[0]
    if code.startswith(("688", "689")):
        base = GROWTH_BOARD_LIMIT if trade_date >= STAR_BOARD_OPEN_DATE else MAIN_BOARD_LIMIT
    elif code.startswith(("300", "301")):
        base = (
            GROWTH_BOARD_LIMIT
            if trade_date >= CHINEXT_REGISTRATION_DATE
            else MAIN_BOARD_LIMIT
        )
    else:
        base = MAIN_BOARD_LIMIT
    # 仅主板 ST 特殊：新规前 ±5%；其余板块 ST 跟随板块档（参照 price_limit_pct 口径）
    if (
        base == MAIN_BOARD_LIMIT
        and is_risk_warning_name(name)
        and trade_date < MAIN_BOARD_ST_LIMIT_CHANGE_DATE
    ):
        return LEGACY_MAIN_BOARD_ST_LIMIT
    return base
