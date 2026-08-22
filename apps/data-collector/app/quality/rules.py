"""声明式质量规则：每张表一份 QualityRule，字段级/行级分开。

规则只拦「物理不可能 / 明显损坏」，不做统计异常检测（P2 另由统计标记处理，
避免误杀真实异动）。新增一张表的规则 = 在 RULES 里登记一份，不改框架。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from app.quality.models import Severity

# 单行规则返回 None（合格）或 (severity, reason)
RowRule = Callable[[dict[str, Any]], tuple[Severity, str] | None]


@dataclass(frozen=True)
class QualityRule:
    """一张表的质量规则集合。"""

    table: str
    # 必要字段（缺失即 P0）
    required_fields: tuple[str, ...] = ()
    # OHLC 类表标记：开启 OHLC 自洽 + 价格/量非负校验
    ohlc: bool = False
    # 涨跌幅物理边界（小数，如 0.30 = ±30%）；None 不校验
    max_change_pct: float | None = None
    # 涨跌幅字段名（各表不一）
    change_pct_field: str = "change_percent"
    # 行级自定义规则（表特有）
    row_rules: tuple[RowRule, ...] = ()
    # symbol 字段名（各表不一）
    symbol_field: str = "symbol"
    # 数值非负字段（如市值/计数/成交额，为负即 P0 物理不可能）
    non_negative_fields: tuple[str, ...] = ()
    # P2 统计检测（批级，只标记不拦）：
    # zscore_field 非空则对该字段做批内 Z-score 离群标记；daily_gap=True 做日K 跳空标记
    zscore_field: str | None = None
    daily_gap: bool = False


def _fnum(v: Any) -> float | None:
    """宽松转 float；失败/NaN 返回 None。"""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else f


def _check_ohlc(row: dict[str, Any]) -> tuple[Severity, str] | None:
    """OHLC 自洽 + 价格/量非负（P0 物理不可能）。"""
    o = _fnum(row.get("open"))
    h = _fnum(row.get("high"))
    low = _fnum(row.get("low"))
    c = _fnum(row.get("close"))

    for name, v in (("open", o), ("high", h), ("low", low), ("close", c)):
        if v is not None and v < 0:
            return (Severity.P0, f"{name} 为负: {v}")

    if h is not None and low is not None and h < low:
        return (Severity.P0, f"high({h}) < low({low})")
    if h is not None and c is not None and c > h:
        return (Severity.P0, f"close({c}) > high({h})")
    if low is not None and c is not None and c < low:
        return (Severity.P0, f"close({c}) < low({low})")
    if h is not None and o is not None and o > h:
        return (Severity.P0, f"open({o}) > high({h})")
    if low is not None and o is not None and o < low:
        return (Severity.P0, f"open({o}) < low({low})")

    vol = _fnum(row.get("volume"))
    if vol is not None and vol < 0:
        return (Severity.P0, f"volume 为负: {vol}")
    return None


def _check_change_pct(rule: QualityRule, row: dict[str, Any]) -> tuple[Severity, str] | None:
    """涨跌幅物理边界（P1 明显损坏）。"""
    if rule.max_change_pct is None:
        return None
    pct = _fnum(row.get(rule.change_pct_field))
    if pct is None:
        return None
    if abs(pct) > rule.max_change_pct:
        return (
            Severity.P1,
            f"{rule.change_pct_field} 越界: {pct}（阈值 ±{rule.max_change_pct}）",
        )
    return None


def _check_non_negative(rule: QualityRule, row: dict[str, Any]) -> tuple[Severity, str] | None:
    """数值非负（P0 物理不可能）：市值/计数/成交额等为负即损坏。"""
    for f in rule.non_negative_fields:
        v = _fnum(row.get(f))
        if v is not None and v < 0:
            return (Severity.P0, f"{f} 为负: {v}")
    return None


# ── 各表规则登记 ─────────────────────────────────────────────
# OHLC 类表开 ohlc=True；涨跌幅阈值按市场物理边界取最宽（CN 北交所 30% 最宽；
# US/HK 无硬限但 >100% 视为损坏）。

RULES: dict[str, QualityRule] = {
    "daily_prices": QualityRule(
        table="daily_prices",
        required_fields=("symbol", "date", "close"),
        ohlc=True,
        daily_gap=True,  # P2：日K 跳空标记
    ),
    "quote_snapshots": QualityRule(
        table="quote_snapshots",
        required_fields=("symbol", "last_price"),
        max_change_pct=1.0,  # |涨跌| > 100% 视为损坏（跨市场最宽）
    ),
    "index_prices": QualityRule(
        table="index_prices",
        required_fields=("symbol", "date", "close"),
    ),
    "macro_asset_prices": QualityRule(
        table="macro_asset_prices",
        required_fields=("symbol", "date", "close"),
    ),
    # ── 数值榜单/指标表 ──
    "movers_cache": QualityRule(
        table="movers_cache",
        required_fields=("symbol", "type", "market", "snapshot_date"),
        max_change_pct=10.0,  # 榜单 percent_change 极端容错（>1000% 视为损坏）
        change_pct_field="percent_change",
        non_negative_fields=("volume", "amount"),
        zscore_field="percent_change",  # P2：榜单内离群标记
    ),
    "fund_flow": QualityRule(
        table="fund_flow",
        required_fields=("symbol", "snapshot_date"),
        # 东财 change_percent 为百分数口径（如 9.96 = 9.96%），阈值按百分数设 ±40
        # （覆盖科创/创业/北交所涨停 20%/30%，留余量；曾按小数设 ±1.0 有误拦风险）
        max_change_pct=40.0,
        non_negative_fields=("amount_in", "amount_out", "amount_total"),
        # net_amount 可为负（净流出），不设非负
        zscore_field="net_amount",  # P2：资金流净额离群标记
    ),
    "board_heat": QualityRule(
        table="board_heat",
        required_fields=("board_type", "name", "snapshot_date"),
        # 板块 change_percent 为百分数口径（东财原值，9.96 = 9.96%），
        # 阈值按百分数设 ±50（板块单日 ±50% 才视为损坏；曾误设 ±1.0 致大量误拦）
        max_change_pct=50.0,
        non_negative_fields=("market_cap",),
    ),
    "analyst_consensus": QualityRule(
        table="analyst_consensus",
        required_fields=("symbol", "snapshot_date"),
        non_negative_fields=("number_of_analysts",),
    ),
    "market_breadth": QualityRule(
        table="market_breadth",
        required_fields=("date", "market"),
        non_negative_fields=(
            "up_count", "down_count", "flat_count",
            "limit_up_count", "limit_down_count",
        ),
    ),
    # ── 基本面/宏观表 ──
    "fundamental_metrics": QualityRule(
        table="fundamental_metrics",
        required_fields=("symbol",),
        non_negative_fields=("market_cap",),
    ),
    "macro_indicators": QualityRule(
        table="macro_indicators",
        required_fields=("name", "date", "value"),
    ),
    "equity_profiles": QualityRule(
        table="equity_profiles",
        required_fields=("symbol",),
        non_negative_fields=("market_cap",),
    ),
    "income_statements": QualityRule(
        table="income_statements",
        required_fields=("symbol", "fiscal_year"),
    ),
    "balance_sheets": QualityRule(
        table="balance_sheets",
        required_fields=("symbol", "period", "fiscal_date"),
    ),
    "cash_flow_statements": QualityRule(
        table="cash_flow_statements",
        required_fields=("symbol", "period", "fiscal_date"),
    ),
}


def get_rule(table: str) -> QualityRule | None:
    return RULES.get(table)


def validate_row(rule: QualityRule, row: dict[str, Any]) -> tuple[Severity, str] | None:
    """按规则校验单行，返回 (severity, reason) 或 None。"""
    for f in rule.required_fields:
        if row.get(f) is None:
            return (Severity.P0, f"缺必要字段: {f}")

    if rule.ohlc:
        if (r := _check_ohlc(row)) is not None:
            return r

    if (r := _check_change_pct(rule, row)) is not None:
        return r

    # 数值非负（P0）
    if (r := _check_non_negative(rule, row)) is not None:
        return r

    for rr in rule.row_rules:
        if (r := rr(row)) is not None:
            return r

    return None
