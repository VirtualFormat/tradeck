"""回测结果扩展统计 — 分标的聚合 / 收益分布 / 按日交易明细 / 选择漏斗。

参照 tick-stock-panel 的结果契约口径移植（适配 tradeck 矩阵回测结构）：
- per_symbol_stats：分标的聚合（选股次数/总收益复利/胜率/最佳/最差/总盈亏金额），
  按总收益降序（与参照 _calc_per_symbol 一致）。
- return_distribution：交易净收益率的直方图分桶（默认固定区间 [-20%, +20%]、20 桶，
  与参照一致；clip 到区间边界，前端分布图可直接按桶渲染）。
- daily_trade_rows：按交易日聚合的买卖笔数 + 当日已实现盈亏 + 累计已实现盈亏，
  覆盖净值曲线全部日期（无成交日输出全零行，便于前端逐日对齐渲染）。
- selection_stats：选择漏斗计数。口径说明（务必先看注释再消费）：
  tradeck 的过滤分两层——策略 basic_filter 发生在矩阵构建/信号产出层（被滤标的
  不产信号，无法在此统计），撮合执行约束层在 matcher 的 continue 路径上
  （涨跌停不可成交/超仓位上限不开仓等，当前没有执行期计数器）。
  本函数只统计「能准确统计」的部分：
  - signals_entry / signals_exit：策略产出的买/卖信号日总数（信号右移前口径）。
  - filled_trades：实际成交笔数（闭环交易数）。
  涨跌停阻止买/卖、超仓位上限放弃等执行期计数，须待 matcher 增加计数器后补充，
  此处不硬凑（宁缺勿假）。
"""
from __future__ import annotations

from datetime import date

import numpy as np

from app.engine.matcher import Trade

# 收益分布默认分桶口径（与参照 tick-stock-panel 一致：±20% 固定区间 20 桶，
# 交易净收益 clip 到边界，超出部分并入最外桶）
_DIST_LO, _DIST_HI = -0.20, 0.20


def per_symbol_stats(
    trades: list[Trade], names: dict[str, str] | None = None
) -> list[dict]:
    """分标的聚合：选股次数/总收益(复利)/胜率/最佳/最差/总盈亏金额，按总收益降序。

    空输入返回 []（优雅降级）。总收益为复利口径 ∏(1+ret)-1；
    total_pnl 为净盈亏金额直接求和（非复利，仅作规模参考）。
    names 提供时附中文名（无名称标的缺省 None）。
    """
    if not trades:
        return []
    by_sym: dict[str, dict] = {}
    for t in trades:
        d = by_sym.setdefault(t.symbol, {
            "symbol": t.symbol, "n_trades": 0, "total_return": 1.0,
            "best": -np.inf, "worst": np.inf, "wins": 0, "total_pnl": 0.0,
        })
        d["n_trades"] += 1
        d["total_return"] *= 1.0 + t.ret
        d["best"] = max(d["best"], t.ret)
        d["worst"] = min(d["worst"], t.ret)
        d["total_pnl"] += t.pnl
        if t.ret > 0:
            d["wins"] += 1
    out = [
        {
            "symbol": d["symbol"],
            "name": (names or {}).get(d["symbol"]),
            "n_trades": d["n_trades"],
            "total_return": round(d["total_return"] - 1.0, 4),
            "win_rate": round(d["wins"] / d["n_trades"], 4) if d["n_trades"] else 0.0,
            "best": round(float(d["best"]), 4),
            "worst": round(float(d["worst"]), 4),
            "total_pnl": round(float(d["total_pnl"]), 2),
        }
        for d in by_sym.values()
    ]
    return sorted(out, key=lambda x: x["total_return"], reverse=True)


def return_distribution(trades: list[Trade], bins: int = 20) -> list[dict]:
    """交易净收益率分布直方图（固定 ±20% 区间分桶，clip 到边界）。

    每个桶输出 {"bucket_start", "bucket_end"（小数区间，前端染色/标签用）,
    "range"（预格式化文案）, "count", "ratio"}；超界样本并入最外桶（P2 登记：
    展示侧可用 range 文案区分「含超界」）。
    空输入返回 []（优雅降级，前端空态处理）。bins <= 0 按默认 20 处理。
    """
    if not trades:
        return []
    if bins <= 0:
        bins = 20
    pnls = np.array([t.ret for t in trades], dtype=float)
    pnls = pnls[np.isfinite(pnls)]  # 剔除 nan/inf，防直方图计数失真
    if pnls.size == 0:
        return []
    clipped = np.clip(pnls, _DIST_LO, _DIST_HI)
    counts, edges = np.histogram(clipped, bins=bins, range=(_DIST_LO, _DIST_HI))
    return [
        {
            "bucket_start": round(float(edges[i]), 4),
            "bucket_end": round(float(edges[i + 1]), 4),
            "range": f"{edges[i] * 100:+.0f}~{edges[i + 1] * 100:+.0f}%",
            "count": int(counts[i]),
            "ratio": round(float(counts[i] / pnls.size), 4),
        }
        for i in range(bins)
    ]


def daily_trade_rows(
    trades: list[Trade],
    equity_dates: list[date],
    equity: list[float],
) -> list[dict]:
    """按交易日聚合：买入笔数/卖出笔数/当日已实现盈亏/累计已实现盈亏。

    覆盖净值曲线全部日期（zip 对齐 equity_dates/equity），无成交日输出全零行，
    便于前端与净值曲线逐日对齐渲染。日期不一致时按 zip 短截（优雅降级）。
    已实现盈亏按 exit_date 归属（买入日记笔数不记盈亏，与撮合现金口径一致：
    成本在买入时已扣，卖出日盈亏为净额）。
    """
    if not equity_dates or not equity:
        return []
    # 买入笔数按 entry_date 聚合；卖出笔数 + 已实现盈亏按 exit_date 聚合
    buys: dict[date, int] = {}
    sells: dict[date, tuple[int, float]] = {}
    for t in trades:
        buys[t.entry_date] = buys.get(t.entry_date, 0) + 1
        n, pnl = sells.get(t.exit_date, (0, 0.0))
        sells[t.exit_date] = (n + 1, pnl + t.pnl)
    rows: list[dict] = []
    cum = 0.0
    for d, v in zip(equity_dates, equity):
        n_sell, day_pnl = sells.get(d, (0, 0.0))
        cum += day_pnl
        rows.append({
            "date": d.isoformat(),
            "buys": buys.get(d, 0),
            "sells": n_sell,
            "realized_pnl": round(day_pnl, 2),
            "cumulative_pnl": round(cum, 2),
            "equity": float(v),
        })
    return rows


def selection_stats(
    signals_entry_count: int,
    signals_exit_count: int,
    filled_trades: int,
) -> dict:
    """选择漏斗计数（口径见模块 docstring；只统计能准确统计的部分）。

    - signals_entry / signals_exit：策略产出的买/卖信号日总数。
    - filled_trades：实际成交的闭环交易笔数。
    执行层拦截（涨跌停/超仓位上限）当前 matcher 无计数器，待补充后扩展，
    此处明确不输出猜测值（宁缺勿假）。
    """
    return {
        "signals_entry": int(signals_entry_count),
        "signals_exit": int(signals_exit_count),
        "filled_trades": int(filled_trades),
    }
