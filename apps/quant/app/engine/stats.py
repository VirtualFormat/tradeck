"""回测统计 — 从净值曲线与成交记录算标准指标。

口径：
- 年化按 252 个交易日。
- 夏普用日收益均值/标准差 × √252（无风险利率取 0，报告中标注）。
- 卡玛 = 年化收益 / 最大回撤（绝对值）。
- 胜率/盈亏比基于逐笔净盈亏（已扣成本）。

阶段 K2 对账（2026-09-10，手算黄金值 + numpy 第二实现对拍，误差为 0）：
- annual_return：几何 CAGR = (末值/首值)^(252/收益条数) - 1。
- max_drawdown：净值 / 历史峰值 - 1 的全程最小值（相对回撤，非绝对金额）。
- sharpe：标准差取 ddof=0（总体口径）。部分第三方库（如 empyrical）默认
  ddof=1（样本口径），换算关系 sharpe_ddof0 = sharpe_ddof1 × √(n/(n-1))；
  本方差口径为既定约定，维持不变。
- sortino：下行偏差取负收益样本的 ddof=0 标准差（相对自身均值的离散度），
  与「相对目标收益的下行偏差」口径不同，两种定义均常见，此处沿用前者。
- 零波动保护：标准差为 0 时 sharpe/sortino 降级为 0.0（不输出 NaN/inf）。
- 蒙特卡洛最大回撤（mc_maxdd_p50/p95，2026-09-12 新增，参照
  tick-stock-panel engine.py _mc_drawdown_percentiles 口径）：
  对日收益序列做 bootstrap 重排（有放回重抽样），每次重排算一条净值曲线的
  最大回撤，取回撤分布的分位数——回答「仅因收益顺序运气，回撤能有多坏」。
  p50 = 中位场景最大回撤；p95 = 95% 置信最坏场景（= 分布 5 分位，更负）。
  固定种子保证可复现；日收益样本 <3 无统计意义，返回 None（对齐空口径）。
"""
from __future__ import annotations

import numpy as np

from app.engine.matcher import SimResult


# 蒙特卡洛回撤估计的模拟次数与种子（固定保证可复现/可测）
_MC_N_SIMS = 1000
_MC_SEED = 42


def _mc_maxdd(rets: np.ndarray, n_sims: int = _MC_N_SIMS) -> tuple[float | None, float | None]:
    """日收益序列的 bootstrap 最大回撤分位估计（p50 / p95 最坏场景）。

    参照 tick-stock-panel _mc_drawdown_percentiles 口径（原实现对交易 pnl 重排，
    本方差对日收益重排——口径差异在注释标注；语义同为「收益顺序运气对回撤的影响」）：
    - 剔除 nan/inf；单日收益 clip 到 >= -99.99%（防御 cumprod 得非正净值）。
    - 样本 <3 返回 (None, None)（无统计意义，与空骨架口径一致）。
    - 内存护栏：samples/equity/peak/dd 各占 eff_sims*n*8B，控总单元 <= 2M。
    - 固定种子（default_rng(_MC_SEED)）保证两次调用结果一致（可复现）。
    """
    rets = np.asarray(rets, dtype=float)
    rets = rets[np.isfinite(rets)]  # 剔除 inf/nan，否则 cumprod 传播 nan
    # 防御：单日收益 <= -100% 时 (1+r) <= 0 让 cumprod 符号翻转/得非正净值，回撤失真。
    # 实际回测有止损不会发生；兜底 clip 到 -99.99% 保证 (1+r) 恒正。
    rets = np.clip(rets, -0.9999, None)
    n = len(rets)
    if n < 3:
        return None, None
    # 内存护栏：samples/equity/peak/dd 各占 eff_sims*n*8B，控总单元 <= 2M（~64MB 峰值）
    eff_sims = min(n_sims, max(200, 2_000_000 // n))
    rng = np.random.default_rng(_MC_SEED)
    samples = rng.choice(rets, size=(eff_sims, n), replace=True)
    equity = np.cumprod(1.0 + samples, axis=1)
    peak = np.maximum.accumulate(equity, axis=1)
    dd = (equity - peak) / peak
    maxdds = dd.min(axis=1)
    return (
        round(float(np.percentile(maxdds, 50)), 4),
        round(float(np.percentile(maxdds, 5)), 4),
    )


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
    # 蒙特卡洛最大回撤（bootstrap 重排日收益，口径见模块 docstring）
    mc_p50, mc_p95 = _mc_maxdd(rets)
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
        "mc_maxdd_p50": mc_p50,
        "mc_maxdd_p95": mc_p95,
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
        "mc_maxdd_p50": None, "mc_maxdd_p95": None,
        "days": len(result.equity), "final_value": result.final_value,
        "unadjusted": result.unadjusted, "risk_free_rate": 0.0,
    }
