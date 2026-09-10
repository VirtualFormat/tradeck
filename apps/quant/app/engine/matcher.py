"""撮合引擎 — 信号矩阵 → 成交记录 → 逐日净值（防未来函数是铁规矩）。

口径（参照 tick-stock-panel MatcherConfig 精简实现，三市场参数化）：
- 信号当日收盘产生，open_t+1 成交（默认）：信号右移 1 日、用次日 open 成交。
  close_t 口径为「研究用理想价」，报告中须标注。
- 成本：佣金双边 + 印花税仅卖出（CN/HK）+ 滑点双边（bps）。
- 约束开关（默认全开）：CN T+1（当日买不可卖）、CN 涨跌停不可成交、整手 100 股（仅 CN）。
- 仓位：等权分配（max_positions 上限内逐信号开仓）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import numpy as np

from app.engine.limits import limit_pct
from app.matrix import MarketMatrix


@dataclass
class CostModel:
    """分市场成本模型（小数口径；滑点为基点 bps）。"""
    commission_pct: float = 0.00025   # 佣金双边
    min_commission: float = 0.0       # 单笔最低佣金（CN 5 元）
    stamp_tax_pct: float = 0.0        # 印花税（仅卖出）
    slippage_bps: float = 10.0        # 滑点双边（bps = 万分之一）

    def buy_cost(self, value: float) -> float:
        c = max(value * self.commission_pct, self.min_commission if value > 0 else 0.0)
        return c + value * self.slippage_bps / 10000.0

    def sell_cost(self, value: float) -> float:
        c = max(value * self.commission_pct, self.min_commission if value > 0 else 0.0)
        return c + value * self.stamp_tax_pct + value * self.slippage_bps / 10000.0


# 三市场默认成本（docs/QUANT-BACKTEST.md 口径）
COST_CN = CostModel(commission_pct=0.00025, min_commission=5.0, stamp_tax_pct=0.001, slippage_bps=100)
COST_US = CostModel(commission_pct=0.0, min_commission=0.0, stamp_tax_pct=0.0, slippage_bps=50)
COST_HK = CostModel(commission_pct=0.0003, min_commission=0.0, stamp_tax_pct=0.001, slippage_bps=100)


def _cost_of(symbol: str, commission_pct: float | None = None) -> CostModel:
    """分市场成本模型；commission_pct 显式给出时覆盖默认佣金（其余成本项不变）。"""
    if symbol.endswith((".SH", ".SS", ".SZ", ".BJ")):
        base = COST_CN
    elif symbol.endswith(".HK"):
        base = COST_HK
    else:
        base = COST_US
    if commission_pct is None:
        return base
    return CostModel(
        commission_pct=commission_pct,
        min_commission=base.min_commission,
        stamp_tax_pct=base.stamp_tax_pct,
        slippage_bps=base.slippage_bps,
    )


def _is_cn(symbol: str) -> bool:
    return symbol.endswith((".SH", ".SS", ".SZ", ".BJ"))


@dataclass
class MatcherConfig:
    """撮合配置。"""
    entry_fill: str = "open_t+1"   # open_t+1（默认，防未来函数）/ close_t（研究口径）
    exit_fill: str = "open_t+1"
    initial_capital: float = 1_000_000.0
    max_positions: int = 10          # 最大同时持仓数
    commission_pct: float | None = None  # 佣金率覆盖（小数），None=用分市场默认
    t1: bool = True                  # CN T+1：当日买不可卖
    price_limit: bool = True         # CN 涨跌停不可成交
    lot_size: bool = True            # CN 整手 100 股
    stop_loss_pct: float | None = None    # 止损（如 -0.08），None 关闭
    take_profit_pct: float | None = None  # 止盈，None 关闭
    # 移动止损：相对持仓期峰值价（含当日 high）回撤超过该比例即离场（如 0.05 表示
    # 从峰值回落 5% 触发）；None 关闭。语义对齐参照 tick-stock-panel MatcherConfig。
    trailing_stop_pct: float | None = None
    # 移动止盈（回撤止盈）：峰值收益先达到 activate_pct 才激活（如 0.10 = 峰值浮盈
    # ≥10% 激活），激活后从峰值回撤超过 drawdown_pct 触发离场；两者须同时设置，None 关闭。
    trailing_take_profit_activate_pct: float | None = None
    trailing_take_profit_drawdown_pct: float | None = None
    max_hold_days: int | None = None      # 最长持有交易日数，None 不限


@dataclass
class Trade:
    symbol: str
    entry_date: date
    exit_date: date
    entry_price: float   # 成交价（与信号矩阵同口径，复权价）
    exit_price: float
    shares: float
    pnl: float           # 净盈亏（已扣双边成本）
    ret: float           # 收益率（净）
    exit_reason: str     # signal / stop_loss / take_profit / trailing_stop /
                         # trailing_take_profit / max_hold / end


@dataclass
class SimResult:
    trades: list[Trade] = field(default_factory=list)
    equity_dates: list[date] = field(default_factory=list)
    equity: list[float] = field(default_factory=list)   # 逐日组合净值（含现金）
    final_value: float = 0.0
    unadjusted: list[str] = field(default_factory=list)  # 无复权降级标的（报告标注用）


def _cn_limit_prices(
    prev_close: float, symbol: str, trade_date: date, name: str = ""
) -> tuple[float, float]:
    """CN 涨跌停价（板块/日期/ST 分档见 engine.limits.limit_pct）。"""
    pct = limit_pct(symbol, trade_date, name)
    return prev_close * (1 - pct), prev_close * (1 + pct)


def simulate(
    matrix: MarketMatrix,
    entries: dict[str, np.ndarray],
    exits: dict[str, np.ndarray],
    config: MatcherConfig,
    adjusted_flags: dict[str, bool] | None = None,
    names: dict[str, str] | None = None,
) -> SimResult:
    """组合撮合模拟：现金统一池，逐日先卖后买，等权分配。

    entries/exits：{symbol: bool 数组}，长度 = len(matrix.dates)，与日期轴对齐
    （信号在收盘后产生）。open_t+1 口径下用「昨日信号 + 今日 open」成交。
    names：symbol → 证券简称（键用 symbol 原样查找）。缺省 None 或缺失标的时
    按无名称降级——即一律按非 ST 分档（宁少拦 ST 不臆造），与历史行为兼容。
    """
    names = names or {}
    dates = matrix.dates
    n = len(dates)
    symbols = matrix.symbols
    close = matrix.close
    openp = matrix.open
    # 峰值跟踪用当日 high；矩阵暂无 high 字段时降级 close（与参照 max_high 口径最接近）
    high = getattr(matrix, "high", None)
    sym_idx = {s: j for j, s in enumerate(symbols)}

    cash = config.initial_capital
    positions: dict[str, dict] = {}
    trades: list[Trade] = []
    equity_dates: list[date] = []
    equity: list[float] = []

    def entry_price_of(i: int, j: int) -> float:
        return openp[i, j] if config.entry_fill == "open_t+1" else close[i, j]

    def exit_price_of(i: int, j: int) -> float:
        return openp[i, j] if config.exit_fill == "open_t+1" else close[i, j]

    def signal_fired(sig: np.ndarray | None, i: int, fill: str) -> bool:
        if sig is None:
            return False
        return (i > 0 and sig[i - 1]) if fill == "open_t+1" else sig[i]

    def blocked_by_limit(i: int, j: int, side: str) -> bool:
        """CN 涨跌停不可成交：buy 遇涨停不开仓，sell 遇跌停不平仓。"""
        if not config.price_limit or not _is_cn(symbols[j]) or i == 0:
            return False
        pc, c = close[i - 1, j], close[i, j]
        if np.isnan(pc) or np.isnan(c):
            return False
        lo, hi = _cn_limit_prices(pc, symbols[j], dates[i], names.get(symbols[j], ""))
        # 一字板判定：收盘价顶死涨/跌停（日K 只能保守判，精确口径需盘中价）
        return c >= hi - 1e-9 if side == "buy" else c <= lo + 1e-9

    for i in range(n):
        # 平仓（先卖后买，释放现金）
        for sym in list(positions):
            j = sym_idx[sym]
            pos = positions[sym]
            c = close[i, j]
            if np.isnan(c):
                continue  # 停牌：不可操作，继续持有
            reason = None
            ret_now = c / pos["entry_price"] - 1.0
            # 峰值跟踪：持仓期最高价（日K 口径用当日 high，缺失降级 close；
            # 参照 tick-stock-panel 用 max_high，同口径）
            h = high[i, j] if high is not None else np.nan
            if not np.isnan(h):
                pos["peak"] = max(pos["peak"], h)
            elif not np.isnan(c):
                pos["peak"] = max(pos["peak"], c)
            peak = pos["peak"]
            # 风控线（止损/移动止损/移动止盈）同日多条成立时取最紧（触发价最高者），
            # 与参照 _risk_exit 的 max(risk_lines) 口径一致。
            risk_lines: list[tuple[float, str]] = []
            if config.stop_loss_pct is not None:
                # 固定止损线（沿用旧语义：stop_loss_pct 为负值，如 -0.08）
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
            # 退出优先级（高→低，对齐参照 tick-stock-panel engine.py TradeRecord 注释：
            # 风控(止损/移动止损/移动止盈) > signal(卖点) > max_hold(到期) > end；
            # 参照另有 pending_exit 历史挂单最高，本引擎无挂单概念故无此项。
            # 注意：旧实现是 signal 优先于固定止损，与参照相反，本次按参照重排——
            # 风控是保护性离场，必须先于策略主动卖点。
            if risk_lines:
                reason = max(risk_lines, key=lambda x: x[0])[1]
            elif signal_fired(exits.get(sym), i, config.exit_fill):
                reason = "signal"
            elif config.take_profit_pct is not None and ret_now >= config.take_profit_pct:
                reason = "take_profit"
            elif config.max_hold_days is not None and i - pos["entry_idx"] >= config.max_hold_days:
                reason = "max_hold"
            if reason is None:
                continue
            # T+1：当日买入不可当日卖出（防御；open_t+1 口径下 entry_idx==i 不会出现）
            if config.t1 and _is_cn(sym) and pos["entry_idx"] == i:
                continue
            if blocked_by_limit(i, j, "sell"):
                continue
            px = exit_price_of(i, j)
            if np.isnan(px):
                continue
            value = pos["shares"] * px
            cost = _cost_of(sym, config.commission_pct).sell_cost(value)
            cash += value - cost
            pnl = (px - pos["entry_price"]) * pos["shares"] - pos["entry_cost"] - cost
            trades.append(Trade(
                symbol=sym, entry_date=pos["entry_date"], exit_date=dates[i],
                entry_price=pos["entry_price"], exit_price=px, shares=pos["shares"],
                pnl=pnl, ret=pnl / (pos["entry_price"] * pos["shares"]),
                exit_reason=reason,
            ))
            del positions[sym]

        # 开仓（等权：可用资金 / 剩余名额）
        slots = config.max_positions - len(positions)
        if slots > 0:
            candidates = []
            for j, sym in enumerate(symbols):
                if sym in positions:
                    continue
                if not signal_fired(entries.get(sym), i, config.entry_fill):
                    continue
                if np.isnan(entry_price_of(i, j)) or np.isnan(close[i, j]):
                    continue
                if blocked_by_limit(i, j, "buy"):
                    continue
                candidates.append(j)
            if candidates:
                budget = cash / min(slots, len(candidates))
                for j in candidates:
                    sym = symbols[j]
                    px = entry_price_of(i, j)
                    # 预算含交易成本：按 (1 + 买入成本率) 预留 + 微小余量（防浮点边界满仓开不了仓）
                    cost_rate = _cost_of(sym, config.commission_pct).buy_cost(1.0)
                    alloc = min(budget, cash / (1.0 + cost_rate + 1e-9))
                    if alloc <= 0:
                        break
                    shares = alloc / px
                    if config.lot_size and _is_cn(sym):
                        shares = np.floor(shares / 100) * 100
                        if shares <= 0:
                            continue
                    value = shares * px
                    cost = _cost_of(sym, config.commission_pct).buy_cost(value)
                    if value + cost > cash:
                        continue
                    cash -= value + cost
                    positions[sym] = {
                        "shares": shares, "entry_price": px,
                        "entry_date": dates[i], "entry_idx": i, "entry_cost": cost,
                        "peak": px,  # 移动止损/移动止盈的峰值跟踪（含当日 high 更新）
                    }

        # 逐日净值（停牌按成本价估值，保守）
        pv = cash
        for sym, pos in positions.items():
            c = close[i, sym_idx[sym]]
            pv += pos["shares"] * (c if not np.isnan(c) else pos["entry_price"])
        equity_dates.append(dates[i])
        equity.append(pv)

    # 期末强平（末日收盘价，计卖出成本；停牌到底按成本记，报告可见）
    last = n - 1
    for sym in list(positions):
        j = sym_idx[sym]
        pos = positions[sym]
        px = close[last, j]
        if np.isnan(px):
            px = pos["entry_price"]
        value = pos["shares"] * px
        cost = _cost_of(sym, config.commission_pct).sell_cost(value)
        pnl = (px - pos["entry_price"]) * pos["shares"] - pos["entry_cost"] - cost
        trades.append(Trade(
            symbol=sym, entry_date=pos["entry_date"], exit_date=dates[last],
            entry_price=pos["entry_price"], exit_price=px, shares=pos["shares"],
            pnl=pnl, ret=pnl / (pos["entry_price"] * pos["shares"]),
            exit_reason="end",
        ))

    result = SimResult(
        trades=trades, equity_dates=equity_dates, equity=equity,
        final_value=equity[-1] if equity else config.initial_capital,
    )
    if adjusted_flags is not None:
        result.unadjusted = sorted(s for s, ok in adjusted_flags.items() if not ok)
    return result
