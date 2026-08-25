"""回测统计 — 从净值曲线与成交记录算标准指标。

口径：
- 年化按 252 个交易日。
- 夏普用日收益均值/标准差 × √252（无风险利率取 0，报告中标注）。
- 卡玛 = 年化收益 / 最大回撤（绝对值）。
- 胜率/盈亏比基于逐笔净盈亏（已扣成本）。
"""
from __future__ import annotations

import numpy as np

from app.engine.matcher import SimResult


def compute(result: SimResult) -> dict:
    """从 SimResult 计算标准回测指标；无交易时返回全零骨架（降级不崩）。"""
    equity = np.array(result.equity)
    if equity.size < 2:
        return _empty(result)
    rets = equity[1:] / equity[:-1] - 1.0
    n_days = len(equity)
    total_ret = equity[-1] / equity[0] - 1.0
    ann_ret = (1.0 + total_ret) ** (252.0 / max(n_days - 1, 1)) - 1.0
    # 最大回撤
    peak = np.maximum.accumulate(equity)
    dd = equity / peak - 1.0
    max_dd = float(dd.min())
    ann_vol = float(rets.std(ddof=0) * np.sqrt(252))
    sharpe = float(rets.mean() / rets.std(ddof=0) * np.sqrt(252)) if rets.std(ddof=0) > 0 else 0.0
    calmar = float(ann_ret / abs(max_dd)) if max_dd < 0 else 0.0
    # 索提诺：均值 / 下行偏差 × √252（只惩罚负收益波动）
    downside = rets[rets < 0]
    downside_std = float(downside.std(ddof=0)) if downside.size > 0 else 0.0
    sortino = float(rets.mean() / downside_std * np.sqrt(252)) if downside_std > 0 else 0.0

    wins = [t for t in result.trades if t.pnl > 0]
    losses = [t for t in result.trades if t.pnl <= 0]
    win_rate = len(wins) / len(result.trades) if result.trades else 0.0
    avg_win = float(np.mean([t.pnl for t in wins])) if wins else 0.0
    avg_loss = float(abs(np.mean([t.pnl for t in losses]))) if losses else 0.0
    pl_ratio = (avg_win / avg_loss) if avg_loss > 0 else 0.0
    # 换手率：成交总额 / 平均资产（近似口径，年化）
    turnover_value = sum(t.shares * (t.entry_price + t.exit_price) for t in result.trades)
    avg_equity = float(equity.mean())
    turnover = (turnover_value / avg_equity) if avg_equity > 0 else 0.0
    # 平均持仓天数（交易日）
    durations = [(t.exit_date - t.entry_date).days for t in result.trades]
    avg_hold_days = float(np.mean(durations)) if durations else 0.0
    # 卖出归因：按 exit_reason 分组统计（胜率/平均盈亏/笔数/总盈亏）
    exit_breakdown: dict[str, dict] = {}
    for t in result.trades:
        b = exit_breakdown.setdefault(
            t.exit_reason, {"count": 0, "wins": 0, "total_pnl": 0.0, "pnls": []}
        )
        b["count"] += 1
        b["wins"] += 1 if t.pnl > 0 else 0
        b["total_pnl"] += t.pnl
        b["pnls"].append(t.pnl)
    exit_stats = {
        reason: {
            "count": b["count"],
            "win_rate": b["wins"] / b["count"] if b["count"] else 0.0,
            "total_pnl": float(b["total_pnl"]),
            "avg_pnl": float(np.mean(b["pnls"])) if b["pnls"] else 0.0,
        }
        for reason, b in exit_breakdown.items()
    }

    return {
        "total_return": float(total_ret),
        "annual_return": float(ann_ret),
        "max_drawdown": max_dd,
        "annual_volatility": ann_vol,
        "sharpe": sharpe,
        "sortino": sortino,
        "calmar": calmar,
        "trades": len(result.trades),
        "win_rate": float(win_rate),
        "profit_loss_ratio": float(pl_ratio),
        "turnover": float(turnover),
        "avg_hold_days": avg_hold_days,
        "exit_stats": exit_stats,
        "days": n_days,
        "final_value": float(equity[-1]),
        "unadjusted": result.unadjusted,
        "risk_free_rate": 0.0,  # 夏普口径标注
    }


def _empty(result: SimResult) -> dict:
    return {
        "total_return": 0.0, "annual_return": 0.0, "max_drawdown": 0.0,
        "annual_volatility": 0.0, "sharpe": 0.0, "sortino": 0.0, "calmar": 0.0,
        "trades": len(result.trades), "win_rate": 0.0, "profit_loss_ratio": 0.0,
        "turnover": 0.0, "avg_hold_days": 0.0, "exit_stats": {},
        "days": len(result.equity), "final_value": result.final_value,
        "unadjusted": result.unadjusted, "risk_free_rate": 0.0,
    }
