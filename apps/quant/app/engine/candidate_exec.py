"""全量候选独立执行引擎 — 每个买入信号一个独立样本，不受资金池/持仓数限制。

参照 tick-stock-panel engine.py 的 simulate_independent_candidates_legacy +
_calc_independent_candidate_result 移植（矩阵轴适配：tradeck 是 (交易日 × 标的)
二维数组，参照是 panel 行轴）。用途是评估策略本身的选股质量，与 matcher.simulate
的组合模拟（现金统一池 + max_positions）互不影响。

口径决策（与参照的差异及原因，改动前必读）：
- 每个买入信号独立执行，固定 100 股（1 手），并行持有无限仓位；同一标的前后
  多个信号各开各的仓，互不挤压。
- 建仓/清仓成交价口径与 matcher 一致：open_t+1 用「昨日信号 + 今日 open」成交，
  close_t 用信号日收盘。
- 风控退出保留 tradeck matcher 的「收盘触发」口径（ret_now / peak 判定、按
  exit_fill 口径成交），不移植参照的盘中触及成交（open/low 触及线即按线价或
  开盘价成交）：保持与同仓库组合模拟同一语义，合成矩阵可手算对拍。
- 风控退出**不复用 matcher 的冷却语义**（_RISK_EXIT_REASONS 退出后须信号复位
  才许重开）：独立执行下每个信号本来就各开各的仓，无「同一信号沿重开」问题，
  刻意不需要冷却——不是漏移植（review P2-2 登记）。
- 退出优先级（参照对齐）：pending_exit 挂单 > 风控（最紧线归因）> signal >
  take_profit > max_hold > end。T+1 约束隐含成立（持仓从成交日次日起检查）。
- 涨跌停拦截为 CN 一字板判定（OHLC 同价 + 收盘顶死涨/跌停价），判定函数与
  参照 _is_one_price_limit 一致；跌停时置 pending_exit 次日开盘强平（参照语义，
  不再次日重评估退出条件）——与 matcher 常规卖出「次日重新评估」不同，此处
  刻意对齐参照。
- 停牌判定（OHLC 全无效 或 volume<=0 且一字价）：买入/卖出当日停牌即不可成交；
  卖出停牌不置 pending_exit（停牌结束后重新评估退出条件，与参照一致）。
- 成本复用 matcher._cost_of_with_overrides（分市场佣金/印花税/滑点；绝对口径
  元/笔），不用参照的 buy_cost_pct 比例口径。
- 样本收益统计（_candidate_stats）：按退出日聚合当日全部样本平均收益 → 日复利
  构造「样本收益曲线」。注意：它不是账户净值，仅反映每日了结样本的平均表现
  的复利外推，用于横向比较策略选股质量。
- per_symbol_stats 复用共享 Trade dataclass（matcher.Trade）：样本交易与组合
  交易同构（shares 恒 100），不新建 CandidateTrade，避免聚合函数双实现。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import numpy as np

from app.engine.limits import limit_pct
from app.engine.matcher import (
    MatcherConfig,
    Trade,
    _cost_of_with_overrides,
    _is_cn,
)
from app.engine.result_stats import per_symbol_stats, return_distribution
from app.matrix import MarketMatrix

# 独立样本固定股数（1 手）；每笔样本名义规模一致，收益直接可比
CANDIDATE_SHARES = 100.0


@dataclass
class CandidateExecResult:
    """全量候选执行结果（样本口径，非账户净值）。"""
    trades: list[Trade] = field(default_factory=list)
    # 样本收益曲线（按退出日聚合平均收益的日复利，起点 1.0；非账户净值）
    sample_dates: list[date] = field(default_factory=list)
    sample_equity: list[float] = field(default_factory=list)
    n_candidates: int = 0            # 原始买入信号日总数（信号右移前口径）
    unadjusted: list[str] = field(default_factory=list)  # 无复权降级标的（报告标注用）
    # 执行期约束计数器，key 口径（同一候选同一分支最多 +1；pending_exit 挂单
    # 跨日重试的每个拦截日各 +1）：
    # - buy_limit_up：信号成交日一字涨停放弃开仓。
    # - buy_suspended：信号成交日停牌（OHLC 全无效 / volume<=0 且一字价）放弃开仓。
    # - buy_invalid_price：成交价无效（NaN/<=0）放弃开仓。
    # - buy_no_next_bar：信号落在末日（无次日 bar 可成交）放弃的候选数
    #   （n_candidates - 可成交信号数，口径同参照）。
    # - sell_limit_down：卖出当日一字跌停拦截次数（置 pending_exit 挂单，
    #   每个跌停日 +1）。
    # - sell_suspended：卖出当日停牌次数（不置挂单，复牌后重评估）。
    # - sell_invalid_price：卖出价无效次数（置 pending_exit 挂单）。
    # - pending_exit：置挂单次数（跌停/无效价卖出拦截后信号确认要卖，次日强平）。
    execution_stats: dict[str, int] = field(default_factory=dict)


def _valid_price(v: float) -> bool:
    return bool(np.isfinite(v)) and v > 0


def simulate_independent(
    matrix: MarketMatrix,
    entries: dict[str, np.ndarray],
    exits: dict[str, np.ndarray],
    config: MatcherConfig,
    names: dict[str, str] | None = None,
    adjusted_flags: dict[str, bool] | None = None,
    progress_cb=None,
    cancel_event=None,
) -> CandidateExecResult:
    """全量候选独立执行：每个买入信号都是独立样本（固定 100 股，无限并行仓位）。

    entries/exits：{symbol: bool 数组}，长度 = len(matrix.dates)，信号在收盘后
    产生（右移口径与 matcher.signal_fired 一致）。
    progress_cb：按候选进度回调 {"day": 已处理候选数, "total": 候选总数, "date"}
    （首个候选必回调一次，此后每 200 个一次 + 末日必回调；键名对齐 matcher
    逐日回调，任务化进度条可直接复用）。
    cancel_event：协作式取消（threading.Event 语义），置位后停止开新样本、
    返回已完成部分（部分结果同样可用，体现在成交笔数 < 候选数上）。
    """
    names = names or {}
    dates = matrix.dates
    n = len(dates)
    symbols = matrix.symbols
    openp, high, low, close = matrix.open, matrix.high, matrix.low, matrix.close
    volume = matrix.volume

    result = CandidateExecResult()
    if adjusted_flags is not None:
        result.unadjusted = sorted(s for s, ok in adjusted_flags.items() if not ok)
    if n == 0:
        return result

    stats = result.execution_stats

    def bump(key: str, by: int = 1) -> None:
        stats[key] = stats.get(key, 0) + by

    def sig_of(sigs: dict[str, np.ndarray], j: int, i: int, fill: str) -> bool:
        """成交日 i 生效的信号（open_t+1 右移一日；close_t 用当日）。"""
        sig = sigs.get(symbols[j])
        if sig is None:
            return False
        if fill == "open_t+1":
            return bool(i > 0 and sig[i - 1])
        return bool(sig[i])

    def is_suspended(i: int, j: int) -> bool:
        """停牌：OHLC 全无效，或 volume<=0 且一字价（一字涨/跌停由下方另判）。"""
        o, h, lo, c = openp[i, j], high[i, j], low[i, j], close[i, j]
        if not any(_valid_price(x) for x in (o, h, lo, c)):
            return True
        v = volume[i, j]
        if np.isfinite(v) and v <= 0:
            same = max(o, h, lo, c) - min(o, h, lo, c) <= max(abs(c) * 1e-4, 0.01)
            if same:
                return True
        return False

    def one_price_limit(i: int, j: int, direction: str) -> bool:
        """CN 一字板判定（OHLC 同价 + 收盘顶死涨/跌停价；与参照 _is_one_price_limit 一致）。

        非一字（盘中有过打开）按可成交处理——日K 无法判盘中开合，保守放行。
        """
        if not config.price_limit or not _is_cn(symbols[j]) or i == 0:
            return False
        if is_suspended(i, j):
            return False
        o, h, lo, c = openp[i, j], high[i, j], low[i, j], close[i, j]
        if not all(_valid_price(x) for x in (o, h, lo, c)):
            return False
        same = max(o, h, lo, c) - min(o, h, lo, c) <= max(abs(c) * 1e-4, 0.01)
        if not same:
            return False
        pc = close[i - 1, j]
        if not _valid_price(pc):
            return False
        pct = limit_pct(symbols[j], dates[i], names.get(symbols[j], ""))
        if direction == "up":
            return c >= pc * (1 + pct) - 1e-9
        return c <= pc * (1 - pct) + 1e-9

    def can_buy(i: int, j: int) -> str:
        """返回拦截原因；空串表示可成交。"""
        if is_suspended(i, j):
            return "buy_suspended"
        px = openp[i, j] if config.entry_fill == "open_t+1" else close[i, j]
        if not _valid_price(px):
            return "buy_invalid_price"
        if one_price_limit(i, j, "up"):
            return "buy_limit_up"
        return ""

    def can_sell(i: int, j: int, px: float) -> str:
        """返回拦截原因；空串表示可成交。"""
        if is_suspended(i, j):
            return "sell_suspended"
        if not _valid_price(px):
            return "sell_invalid_price"
        if one_price_limit(i, j, "down"):
            return "sell_limit_down"
        return ""

    def close_pos(pos: dict, i: int, j: int, reason: str, px: float) -> None:
        """按成交价平仓记一笔样本交易（净盈亏已扣双边成本）。"""
        sym = symbols[j]
        cost_model = _cost_of_with_overrides(
            sym, config.commission_pct, config.stamp_tax_pct, config.slippage_bps
        )
        value = pos["shares"] * px
        sell_cost = cost_model.sell_cost(value)
        pnl = (px - pos["entry_price"]) * pos["shares"] - pos["entry_cost"] - sell_cost
        result.trades.append(Trade(
            symbol=sym,
            entry_date=pos["entry_date"], exit_date=dates[i],
            entry_price=pos["entry_price"], exit_price=px,
            shares=pos["shares"], pnl=pnl,
            ret=pnl / (pos["entry_price"] * pos["shares"]),
            exit_reason=reason,
        ))

    # 候选 = 有成交日的买入信号（末日信号无次日 bar 可成交，计入 buy_no_next_bar）
    candidates: list[tuple[int, int]] = []  # (成交日 i, 标的列 j)
    n_candidates = 0
    for j, _sym in enumerate(symbols):
        ent = entries.get(_sym)
        if ent is None:
            continue
        n_candidates += int(np.count_nonzero(ent))
        for i in range(n):
            if sig_of(entries, j, i, config.entry_fill):
                candidates.append((i, j))
    result.n_candidates = n_candidates
    bump("buy_no_next_bar", max(n_candidates - len(candidates), 0))

    total = len(candidates)
    for seq, (i, j) in enumerate(candidates, start=1):
        if cancel_event is not None and cancel_event.is_set():
            break
        if progress_cb is not None and (seq == 1 or seq % 200 == 0 or seq == total):
            progress_cb({"day": seq, "total": total, "date": dates[i].isoformat()})

        block = can_buy(i, j)
        if block:
            bump(block)
            continue
        sym = symbols[j]
        entry_px = openp[i, j] if config.entry_fill == "open_t+1" else close[i, j]
        entry_cost = _cost_of_with_overrides(
            sym, config.commission_pct, config.stamp_tax_pct, config.slippage_bps
        ).buy_cost(CANDIDATE_SHARES * entry_px)
        pos = {
            "entry_price": entry_px,
            "entry_date": dates[i],
            "shares": CANDIDATE_SHARES,
            "entry_cost": entry_cost,
            "peak": entry_px,  # 峰值跟踪（持仓次日起以当日 high 更新，同 matcher）
            "pending_exit": False,
            "pending_exit_reason": None,
        }
        closed = False
        # 持仓逐日检查：从成交日次日起（T+1 隐含成立）；同日多条成立时
        # 风控最紧线优先于 signal/take_profit/max_hold/end
        for k in range(i + 1, n):
            c = close[k, j]
            if np.isnan(c):
                continue  # 停牌（无收盘价）：不可操作，继续持有
            h = high[k, j]
            if np.isfinite(h):
                pos["peak"] = max(pos["peak"], h)
            else:
                pos["peak"] = max(pos["peak"], c)
            peak = pos["peak"]
            ret_now = c / pos["entry_price"] - 1.0

            if pos["pending_exit"]:
                # pending_exit 挂单（参照语义）：信号已确认要卖，被跌停/无效价
                # 拦截后次日开盘价强平（优先级最高，不重评估退出条件）。
                reason = pos["pending_exit_reason"] or "signal"
                px = openp[k, j]
                block = can_sell(k, j, px)
                if block == "sell_limit_down":
                    bump(block)
                    continue  # 跌停无法成交，挂单保留到明日
                if block:
                    bump(block)
                    continue  # 停牌不置挂单（复牌后重评估）
                close_pos(pos, k, j, reason, px)
                closed = True
                break

            reason: str | None = None
            # 风控线（收盘触发口径，同 matcher：同日多条成立取最紧线归因）
            risk_lines: list[tuple[float, str]] = []
            if config.stop_loss_pct is not None:
                sl_line = pos["entry_price"] * (1 + config.stop_loss_pct)
                if ret_now <= config.stop_loss_pct:
                    risk_lines.append((sl_line, "stop_loss"))
            if config.trailing_stop_pct is not None and peak > 0:
                ts_line = peak * (1 - abs(config.trailing_stop_pct))
                if c <= ts_line:
                    risk_lines.append((ts_line, "trailing_stop"))
            if (config.trailing_take_profit_activate_pct is not None
                    and config.trailing_take_profit_drawdown_pct is not None
                    and peak > pos["entry_price"] > 0):
                peak_ret = peak / pos["entry_price"] - 1.0
                if peak_ret >= abs(config.trailing_take_profit_activate_pct):
                    tp_line = peak * (1 - abs(config.trailing_take_profit_drawdown_pct))
                    if c <= tp_line:
                        risk_lines.append((tp_line, "trailing_take_profit"))
            if risk_lines:
                reason = max(risk_lines, key=lambda x: x[0])[1]
            elif sig_of(exits, j, k, config.exit_fill):
                reason = "signal"
            elif config.take_profit_pct is not None and ret_now >= config.take_profit_pct:
                reason = "take_profit"
            elif config.max_hold_days is not None and k - i >= config.max_hold_days:
                reason = "max_hold"
            if reason is None and k != n - 1:
                continue
            if reason is None:
                # 期末强平（末日）：按末日收盘价成交（与 matcher 期末强平口径
                # 一致，不看 exit_fill——「T 日收盘仍在持仓则以 T 日收盘了结」；
                # 触发顺序在 signal/max_hold 之后：末日有卖出信号按信号口径归因）。
                reason = "end"
                px = c
            else:
                px = openp[k, j] if config.exit_fill == "open_t+1" else c
            block = can_sell(k, j, px)
            if block == "sell_suspended":
                bump(block)
                continue  # 停牌不置挂单：复牌后重新评估退出条件（与参照一致）
            if block:
                # 跌停/无效价：信号已确认要卖 → 置 pending_exit 次日开盘强平
                bump(block)
                if not pos["pending_exit"]:
                    pos["pending_exit"] = True
                    pos["pending_exit_reason"] = reason
                    bump("pending_exit")
                continue
            close_pos(pos, k, j, reason, px)
            closed = True
            break
        if not closed:
            # 持仓到末日仍未退出（如末日停牌循环跳过）：按末日收盘价强平
            # （停牌到底按成本价记，与 matcher 期末强平口径一致）
            last = n - 1
            px = close[last, j]
            if not _valid_price(px):
                px = pos["entry_price"]
            close_pos(pos, last, j, "end", px)

    _build_sample_curve(result)
    return result


def _build_sample_curve(result: CandidateExecResult) -> None:
    """按退出日聚合当日全部样本平均收益 → 日复利（样本收益曲线，非账户净值）。"""
    daily: dict[date, list[float]] = {}
    for t in result.trades:
        daily.setdefault(t.exit_date, []).append(t.ret)
    equity = 1.0
    for d in sorted(daily):
        equity *= 1.0 + float(np.mean(daily[d]))
        result.sample_dates.append(d)
        result.sample_equity.append(equity)


def _candidate_stats(
    trades: list[Trade],
    n_candidates: int,
    benchmark: dict | None = None,
    names: dict[str, str] | None = None,
) -> dict:
    """全量候选统计（样本口径）：选股质量指标，不是账户绩效。

    - avg/median/win_rate/profit_factor/best/worst：逐笔样本净收益分布。
    - profit_factor（盈亏比）= 平均盈利 ÷ 平均亏损绝对值（与参照口径一致；
      无亏损样本时返回 None，对齐参照宁缺勿假）。
    - total_return / max_drawdown / sharpe：基于「样本收益曲线」（按退出日聚合
      平均收益的日复利），仅用于横向比较策略，不可当账户净值解读。
    - n_closed_days = 有样本了结的交易日数；avg_daily_closed = 样本数 / n_closed_days
      （每个了结日平均了结多少笔样本，不是「每日新候选数」）。
    - benchmark 提供时附 excess_return = total_return - 基准区间收益。
    """
    stats: dict = {
        "mode": "full",
        "full_kind": "candidate_execution",
        "n_candidates": int(n_candidates),
        "n_trades": len(trades),
        "n_closed_days": 0,
        "avg_daily_closed": 0.0,
        "avg_return": 0.0,
        "median_return": 0.0,
        "win_rate": 0.0,
        "profit_factor": None,
        "best": 0.0,
        "worst": 0.0,
        "total_return": 0.0,
        "max_drawdown": 0.0,
        "sharpe": 0.0,
        "return_distribution": return_distribution(trades),
        "per_symbol_stats": per_symbol_stats(trades, names=names),
    }
    if benchmark is not None:
        stats["benchmark_symbol"] = benchmark.get("symbol")
        stats["benchmark_return"] = benchmark.get("total_return")
        stats["excess_return"] = None  # 无样本时超额无从谈起（宁缺勿假）
    if not trades:
        return stats

    pnls = np.array([t.ret for t in trades], dtype=float)
    wins = pnls[pnls > 0]
    losses = pnls[pnls <= 0]
    avg_win = float(np.mean(wins)) if len(wins) else 0.0
    avg_loss = abs(float(np.mean(losses))) if len(losses) else 0.0

    # 样本收益曲线（按退出日聚合平均收益的日复利，非账户净值）
    daily: dict[date, list[float]] = {}
    for t in trades:
        daily.setdefault(t.exit_date, []).append(t.ret)
    daily_avg = np.array(
        [float(np.mean(daily[d])) for d in sorted(daily)], dtype=float
    )
    equity = np.cumprod(1.0 + daily_avg)
    # 峰值含起点 1.0：样本收益曲线从 1.0 起算，负收益首日才算回撤
    # （不含起点时首日下跌会被当作「新峰值」而漏计回撤）
    peak = np.maximum.accumulate(np.concatenate(([1.0], equity)))[1:]
    max_dd = float((equity / peak - 1.0).min())
    sharpe = (
        float(daily_avg.mean() / daily_avg.std(ddof=0) * np.sqrt(252))
        if len(daily_avg) > 1 and daily_avg.std(ddof=0) > 0 else 0.0
    )

    stats.update({
        "n_closed_days": len(daily),
        "avg_daily_closed": round(len(trades) / max(len(daily), 1), 1),
        "avg_return": round(float(np.mean(pnls)), 4),
        "median_return": round(float(np.median(pnls)), 4),
        "win_rate": round(float(len(wins) / len(pnls)), 4),
        "profit_factor": round(avg_win / avg_loss, 2) if avg_loss > 0 else None,
        "best": round(float(np.max(pnls)), 4),
        "worst": round(float(np.min(pnls)), 4),
        "total_return": round(float(equity[-1] - 1.0), 4),
        "max_drawdown": round(max_dd, 4),
        "sharpe": round(sharpe, 2),
    })
    if benchmark is not None and benchmark.get("total_return") is not None:
        stats["excess_return"] = round(
            stats["total_return"] - benchmark["total_return"], 4
        )
    return stats
