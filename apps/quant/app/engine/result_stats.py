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
  （涨跌停不可成交/超仓位上限不开仓/冷却跳过等）。
  本函数只统计「能准确统计」的部分：
  - signals_entry / signals_exit：策略产出的买/卖信号日总数（信号右移前口径）。
  - filled_trades：实际成交笔数（闭环交易数）。
  - 执行层拦截计数（M2 起）：matcher 的 execution_stats 传入时，把其中有值的
    拦截键（blocked_buy_limit / blocked_sell_limit / skipped_max_positions /
    skipped_no_cash / skipped_cooldown）并入漏斗；未传入或计数为 0 的键不输出
   （宁缺勿假，键口径见 SimResult.execution_stats 注释）。
- factor_attribution：因子归因（N1，参照 tick-stock-panel「因子归因」Tab）——
  对比盈利单与亏损单入场信号日的因子取值，胜单均值明显高于败单说明该因子有
  正筛选力。对每个指标列算胜/败两组均值 + diff，按 |diff| 降序。
"""
from __future__ import annotations

from datetime import date, timedelta

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
    execution_stats: dict[str, int] | None = None,
) -> dict:
    """选择漏斗计数（口径见模块 docstring；只统计能准确统计的部分）。

    - signals_entry / signals_exit：策略产出的买/卖信号日总数。
    - filled_trades：实际成交的闭环交易笔数。
    - execution_stats（可选）：matcher 执行期约束计数器；仅把值 > 0 的拦截键
      并入输出，缺省/零值不输出（宁缺勿假）。
    """
    out = {
        "signals_entry": int(signals_entry_count),
        "signals_exit": int(signals_exit_count),
        "filled_trades": int(filled_trades),
    }
    for key in (
        "blocked_buy_limit",
        "blocked_sell_limit",
        "skipped_max_positions",
        "skipped_no_cash",
        "skipped_cooldown",
    ):
        v = int((execution_stats or {}).get(key, 0))
        if v > 0:
            out[key] = v
    return out


# ---------------------------------------------------------------------------
# 因子归因（N1）
# ---------------------------------------------------------------------------

# 定位成交行的最大回溯步数（自然日）：分钟成交等口径下 entry_date 可能落在
# 矩阵交易日轴之外（周末/节假日），向前找最近交易日时限步防无限回溯
_SIGNAL_DAY_LOOKBACK_DAYS = 7

# diff 的展示精度（因子原值不 round，原样输出）
_DIFF_ROUND = 6


def _factor_mean(values: list[float]) -> float | None:
    """一组因子值的均值：剔除 NaN 后取均，全 NaN/空组返回 None（优雅降级）。"""
    arr = np.asarray(values, dtype=float)
    arr = arr[~np.isnan(arr)]
    if arr.size == 0:
        return None
    return float(arr.mean())


def factor_attribution(
    enriched,
    trades: list[Trade],
    matrix_symbols: list[str],
    matrix_dates: list[date],
    entry_fill: str = "open_t+1",
) -> dict:
    """因子归因：对比盈利单与亏损单入场信号日的因子取值。

    参照 tick-stock-panel 的「因子归因」Tab：胜单因子均值明显高于败单，
    说明该因子有正筛选力（diff > 0）。

    信号日口径（随 entry_fill 变化，调用方从 MatcherConfig 透传）：
      open_t+1（默认）—— T 日收盘出信号、T+1 开盘成交，
      而 Trade.entry_date 记的是成交日。因此信号日 = 成交日的前一个矩阵交易日：
      在 matrix_dates（矩阵交易日轴，含周末/节假日缺失，故不能用简单的
      entry_date - 1 自然日）里找 entry_date 的索引 i，信号日行 = i - 1。
      close_t（研究口径）—— 信号日即成交日本身（matcher sig_i = i），取行 i。
      分钟口径（minute_* 入场）成交日不变，沿用 open_t+1 口径（i - 1）。
      若 i == 0（成交日即矩阵首个交易日，无更早行），该笔跳过并计入
      skipped_no_signal_day（close_t 口径 i==0 不跳过，信号日行 = 0）。
      若 entry_date 不在矩阵轴上（分钟成交把成交日挪进矩阵区间外的日期），
      向前找最近一个 ≤ entry_date 的矩阵交易日作成交行，再取其前一行作信号日
      （防御口径；正常日K 回测不会走到）。

    分组：ret > 0 为胜组，其余为败组（ret == 0 归败组）。
    对每个指标列分别算两组均值：某组全 NaN 时该组均值为 None（优雅降级，
    diff 也为 None）；diff = win_mean - lose_mean，按 |diff| 降序
    （diff 为 None 的排最后，保持指标名稳定次序）。

    空交易返回骨架 {"factors": [], "n_win": 0, "n_lose": 0,
    "skipped_no_signal_day": 0}。
    """
    assumption = "same_day" if entry_fill == "close_t" else "prev_day"
    empty = {
        "factors": [], "n_win": 0, "n_lose": 0, "skipped_no_signal_day": 0,
        "signal_day_assumption": assumption,
    }
    if not trades:
        return empty

    indicators: dict[str, np.ndarray] = getattr(enriched, "indicators", {}) or {}
    if not indicators or not matrix_dates or not matrix_symbols:
        return empty

    sym_idx = {s: j for j, s in enumerate(matrix_symbols)}
    date_idx = {d: i for i, d in enumerate(matrix_dates)}

    win_vals: dict[str, list[float]] = {name: [] for name in indicators}
    lose_vals: dict[str, list[float]] = {name: [] for name in indicators}
    n_win = n_lose = skipped = 0

    for t in trades:
        j = sym_idx.get(t.symbol)
        if j is None:
            # 交易标的不在矩阵轴上（口径不一致），跳过并计信号日缺失
            skipped += 1
            continue
        # 在矩阵交易日轴上定位成交行：优先精确命中；未命中则向前找最近一个
        # ≤ entry_date 的交易日（限回溯 _SIGNAL_DAY_LOOKBACK_DAYS 步内）
        i: int | None = None
        for step in range(_SIGNAL_DAY_LOOKBACK_DAYS + 1):
            k = date_idx.get(t.entry_date - timedelta(days=step))
            if k is not None:
                i = k
                break
        if i is None or (i == 0 and assumption == "prev_day"):
            # 无信号日行（成交日为矩阵首个交易日，或轴上找不到成交行）
            skipped += 1
            continue
        sig_row = i if assumption == "same_day" else i - 1
        bucket = win_vals if t.ret > 0 else lose_vals
        if t.ret > 0:
            n_win += 1
        else:
            n_lose += 1
        for name, arr in indicators.items():
            bucket[name].append(float(arr[sig_row, j]))

    if n_win == 0 and n_lose == 0:
        # 全部交易都被跳过（无有效信号日），骨架 + 跳过计数
        return {
            "factors": [], "n_win": 0, "n_lose": 0,
            "skipped_no_signal_day": skipped,
            "signal_day_assumption": assumption,
        }

    factors: list[dict] = []
    for name in indicators:
        wm = _factor_mean(win_vals[name])
        lm = _factor_mean(lose_vals[name])
        diff = (
            round(wm - lm, _DIFF_ROUND)
            if wm is not None and lm is not None else None
        )
        factors.append({
            "factor": name,
            "win_mean": wm,
            "lose_mean": lm,
            "diff": diff,
            "n_win": n_win,
            "n_lose": n_lose,
        })
    # 按 |diff| 降序；diff 为 None 的（某组全 NaN）排最后，保持指标名稳定次序
    factors.sort(
        key=lambda f: abs(f["diff"]) if f["diff"] is not None else -1.0,
        reverse=True,
    )
    return {
        "factors": factors,
        "n_win": n_win,
        "n_lose": n_lose,
        "skipped_no_signal_day": skipped,
        "signal_day_assumption": assumption,
    }
