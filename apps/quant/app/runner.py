"""回测管线 — 数据 → 矩阵 → 复权 → 策略 → 撮合 → 统计的最小闭环。

被 CLI run 与后续 HTTP API 共用：给定标的池 + 策略 + 区间，跑出统计结果。
每一环的降级都已内建：缺因子降级无复权标注、策略异常降级空信号、无交易返回全零骨架。
"""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

from app.data import client, factors, store
from app.engine import MatcherConfig, compute, forward_adjust, simulate
from app.matrix import build, enrich
from app.strategy import StrategyRegistry

__all__ = [
    "run_backtest", "run_backtest_async", "compute_empty",
    "user_strategy_dirs", "migrate_legacy_strategy_dirs", "run_backtest_offloaded",
]

logger = logging.getLogger(__name__)

# 主市场基准指数（用于超额收益与净值对比；按标的池多数市场选取）
_BENCHMARK_INDEX = {"CN": "000001.SS", "US": "^GSPC", "HK": "^HSI"}


def _dominant_market(symbols: list[str]) -> str:
    """标的池的多数市场（决定基准指数）。"""
    cn = sum(1 for s in symbols if s.endswith((".SH", ".SS", ".SZ", ".BJ")))
    hk = sum(1 for s in symbols if s.endswith(".HK"))
    us = len(symbols) - cn - hk
    return max((("CN", cn), ("HK", hk), ("US", us)), key=lambda x: x[1])[0]


def _default_user() -> str:
    """未指定用户时的回落值（与 settings.QUANT_DEFAULT_USER 对齐）。"""
    from app.config import settings
    return settings.QUANT_DEFAULT_USER


def _user_root(user_id: str) -> Path:
    """用户命名空间根目录：{QUANT_CACHE_DIR}/users/{user_id}。"""
    from app.config import settings
    return Path(settings.QUANT_CACHE_DIR) / "users" / user_id


def user_strategy_dirs(user_id: str | None = None) -> dict[str, Path]:
    """按用户合成三层策略目录：builtin 全局共享（随包），custom/ai 进用户命名空间。"""
    uid = user_id or _default_user()
    pkg_builtin = Path(__file__).resolve().parent / "strategy" / "builtin"
    base = _user_root(uid) / "strategies"
    return {
        "builtin": pkg_builtin,
        "custom": base / "custom",
        "ai": base / "ai",
    }


# 兼容旧引用（cli/screener/jobs 等仍用 _default_strategy_dirs）
_default_strategy_dirs = user_strategy_dirs


def migrate_legacy_strategy_dirs() -> None:
    """把旧的全局策略目录 {cache}/strategies/{custom,ai} 一次性迁移到 default 用户命名空间。

    幂等：目标已存在（即已迁移过/新结构已建）则跳过；启动时调用一次并 logger.info。
    """
    from app.config import settings
    legacy = Path(settings.QUANT_CACHE_DIR) / "strategies"
    target_root = _user_root(_default_user()) / "strategies"
    for sub in ("custom", "ai"):
        src = legacy / sub
        dst = target_root / sub
        if not src.exists():
            continue
        if dst.exists():
            logger.info("策略目录迁移跳过（目标已存在）：%s → %s", src, dst)
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        src.rename(dst)
        logger.info("策略目录已迁移到 default 用户命名空间：%s → %s", src, dst)


def run_backtest_offloaded(
    symbols: list[str],
    strategy_id: str,
    start: date,
    end: date,
    params: dict | None = None,
    config: "MatcherConfig | None" = None,
    user_id: str | None = None,
) -> dict:
    """经 worker 池跑回测的同步入口（CLI/非事件循环场景用）。

    已在运行事件循环的上下文（HTTP API）请直接 await worker_pool.run_backtest_in_worker。
    """
    import asyncio

    from app.worker import run_backtest_in_worker

    return asyncio.run(run_backtest_in_worker(
        symbols, strategy_id, start, end, params=params, config=config, user_id=user_id,
    ))


async def _fetch_benchmark(
    symbols: list[str], start: date, end: date
) -> dict | None:
    """拉基准指数历史（经 data-api /api/indices），失败降级 None（不阻塞回测）。"""
    market = _dominant_market(symbols)
    symbol = _BENCHMARK_INDEX[market]
    data = await client.get_json("/api/indices", {
        "symbol": symbol,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
    })
    if not data or not isinstance(data, list) or not data:
        return None
    # 按日期升序的收盘序列
    rows = sorted(data, key=lambda r: r["date"])
    closes = [r["close"] for r in rows if r.get("close") is not None]
    if not closes:
        return None
    total_return = closes[-1] / closes[0] - 1.0 if closes[0] else 0.0
    return {
        "symbol": symbol, "market": market,
        "total_return": total_return,
        "dates": [r["date"] for r in rows],
        "closes": closes,
    }


async def _fetch_names(symbols: list[str]) -> dict[str, str]:
    """批量拉证券简称（经 data-api /api/quotes，用于 ST 判定），失败降级空 dict。

    /api/quotes 返回行只含快照表已有标的；缺失标的由撮合层按无名称（非 ST）降级。
    """
    if not symbols:
        return {}
    data = await client.get_json("/api/quotes", {"symbols": ",".join(symbols)})
    if not isinstance(data, list):
        return {}
    return {
        row["symbol"]: row["name"]
        for row in data
        if isinstance(row, dict) and row.get("symbol") and row.get("name")
    }


def run_backtest(
    symbols: list[str],
    strategy_id: str,
    start: date,
    end: date,
    params: dict | None = None,
    config: MatcherConfig | None = None,
    registry: StrategyRegistry | None = None,
    benchmark: dict | None = None,
    names: dict[str, str] | None = None,
) -> dict:
    """跑一个策略在一组标的上的回测，返回统计 + 元信息。

    数据来自本地 Parquet 缓存（调用方应先经 fetch 备数；缺数标的在矩阵层降级为全 NaN 列）。
    benchmark / names 由 async 包装函数 run_backtest_async 预拉取传入（本函数保持同步）。
    names 缺省 None 时撮合按无名称（非 ST）分档，保持历史行为。
    """
    reg = registry or StrategyRegistry(_default_strategy_dirs())
    matrix = build(symbols, start, end)
    if not matrix.dates:
        logger.warning("区间 %s ~ %s 无缓存数据，返回空结果", start, end)
        return {"stats": compute_empty(), "strategy": strategy_id, "symbols": symbols,
                "range": [start.isoformat(), end.isoformat()], "unadjusted": symbols,
                "equity_curve": [], "trades": [], "benchmark": None}

    # 复权：读缓存因子，缺失标的降级无复权并在结果标注
    fac = {s: factors.load(s) for s in symbols}
    adjusted_matrix, adjusted_flags = forward_adjust(matrix, fac)
    enriched = enrich(adjusted_matrix)

    signals = reg.run(strategy_id, enriched, params)
    cfg = config or MatcherConfig()
    result = simulate(
        adjusted_matrix,
        {s: signals.entry[:, j] for j, s in enumerate(adjusted_matrix.symbols)},
        {s: signals.exit[:, j] for j, s in enumerate(adjusted_matrix.symbols)},
        cfg,
        adjusted_flags=adjusted_flags,
        names=names,
    )
    stats = compute(result)
    # 净值曲线（逐日，叠加基准归一化到同一起点便于对比）
    equity_curve = []
    bm = benchmark
    bm_norm: dict[str, float] = {}
    if bm and bm["closes"]:
        base = bm["closes"][0]
        bm_norm = {d: c / base for d, c in zip(bm["dates"], bm["closes"])}
    eq0 = result.equity[0] if result.equity else 1.0
    for d, v in zip(result.equity_dates, result.equity):
        ds = d.isoformat()
        equity_curve.append({
            "date": ds,
            "value": v / eq0 if eq0 else 1.0,           # 归一化（起点=1）
            "benchmark": bm_norm.get(ds),                # 基准归一化（无数据 None）
        })
    # 交易明细（逐笔，含卖出原因与持仓天数）
    trades = [
        {
            "symbol": t.symbol,
            "entry_date": t.entry_date.isoformat(),
            "exit_date": t.exit_date.isoformat(),
            "entry_price": t.entry_price,
            "exit_price": t.exit_price,
            "shares": t.shares,
            "pnl": t.pnl,
            "ret": t.ret,
            "hold_days": (t.exit_date - t.entry_date).days,
            "exit_reason": t.exit_reason,
        }
        for t in result.trades
    ]
    # 基准汇总（区间收益 + 超额）
    benchmark_out = None
    if bm:
        benchmark_out = {
            "symbol": bm["symbol"], "market": bm["market"],
            "total_return": bm["total_return"],
            "excess_return": stats["total_return"] - bm["total_return"],
        }
    return {
        "stats": stats,
        "strategy": strategy_id,
        "symbols": symbols,
        "range": [matrix.dates[0].isoformat(), matrix.dates[-1].isoformat()],
        "unadjusted": result.unadjusted,
        "trades": trades,
        "equity_curve": equity_curve,
        "benchmark": benchmark_out,
    }


async def run_backtest_async(
    symbols: list[str],
    strategy_id: str,
    start: date,
    end: date,
    params: dict | None = None,
    config: MatcherConfig | None = None,
    registry: StrategyRegistry | None = None,
) -> dict:
    """async 包装：先拉基准再跑同步回测（HTTP API 用）。"""
    benchmark = await _fetch_benchmark(symbols, start, end)
    names = await _fetch_names(symbols)
    return run_backtest(
        symbols, strategy_id, start, end, params, config, registry, benchmark, names
    )


def compute_empty() -> dict:
    """无数据时的全零骨架（与 stats.compute 的空口径一致）。"""
    return {
        "total_return": 0.0, "annual_return": 0.0, "max_drawdown": 0.0,
        "annual_volatility": 0.0, "sharpe": 0.0, "calmar": 0.0,
        "trades": 0, "win_rate": 0.0, "profit_loss_ratio": 0.0,
        "turnover": 0.0, "days": 0, "final_value": 0.0, "unadjusted": [],
        "risk_free_rate": 0.0,
    }
