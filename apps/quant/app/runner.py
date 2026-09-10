"""回测管线 — 数据 → 矩阵 → 复权 → 策略 → 撮合 → 统计的最小闭环。

被 CLI run 与后续 HTTP API 共用：给定标的池 + 策略 + 区间，跑出统计结果。
每一环的降级都已内建：缺因子降级无复权标注、策略异常降级空信号、无交易返回全零骨架。
"""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import polars as pl

from app.data import client, factors, store
from app.engine import (
    MatcherConfig, MinuteLoader, compute, forward_adjust, simulate,
)
from app.engine.minute_replay import (
    MINUTE_BARS_PARAM_KEY, MinuteReplayResult, replay_minute_strategy,
)
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
    """批量拉证券简称（用于 ST 判定），失败降级空 dict。

    双源：先 /api/quotes（quote_snapshots，tracked 报价池）；缺失标的兜底
    /api/instruments（instrument_master，全市场含 ST 股）。仍缺由撮合层按无名称
    （非 ST）降级。
    """
    if not symbols:
        return {}
    data = await client.get_json("/api/quotes", {"symbols": ",".join(symbols)})
    names: dict[str, str] = {}
    if isinstance(data, list):
        names = {
            row["symbol"]: row["name"]
            for row in data
            if isinstance(row, dict) and row.get("symbol") and row.get("name")
        }
    # 兜底：quote_snapshots 未覆盖的标的（非 tracked，如 ST 股）从 instrument_master 取
    missing = [s for s in symbols if s not in names]
    if missing:
        # /api/instruments 用 FastAPI list 查询参数（重复 symbols 键，非逗号分隔）
        inst = await client.get_json(
            "/api/instruments", [("symbols", s) for s in missing]
        )
        rows = inst.get("instruments", []) if isinstance(inst, dict) else []
        for row in rows:
            if isinstance(row, dict) and row.get("symbol") and row.get("name"):
                names.setdefault(row["symbol"], row["name"])
    return names


# 分钟K 帧固定数值列序（与 engine/minute_fill.resolve_minute_fill 的整数索引约定一致）
_MINUTE_COLS = ["open", "high", "low", "close", "volume", "amount"]


# ---------------------------------------------------------------------------
# 分钟频策略回放（阶段 H2）
# ---------------------------------------------------------------------------

# 日线面板加载余量：daily_bars 个交易日约需 2× 自然日（周末/节假日），再留预热
_MINUTE_PANEL_CAL_FACTOR = 2
_MINUTE_PANEL_CAL_MARGIN = 30


def _minute_panel_start(start: date, daily_bars: int) -> date:
    """分钟回放的日线面板加载起点：覆盖首个回放日的 daily_bars 根完成态日K 窗口。"""
    from datetime import timedelta
    return start - timedelta(days=max(daily_bars, 1) * _MINUTE_PANEL_CAL_FACTOR
                             + _MINUTE_PANEL_CAL_MARGIN)


def _minute_replay_result_dict(strategy_id: str, symbols: list[str],
                               start: date, end: date,
                               res: MinuteReplayResult) -> dict:
    """MinuteReplayResult → API 返回 dict（分钟回放专属结构，与日K 回测结果区分）。"""
    return {
        "mode": "minute_replay",
        "strategy": strategy_id,
        "symbols": symbols,
        "range": [start.isoformat(), end.isoformat()],
        "replayed_days": res.replayed_days,
        "skipped_days": [d.isoformat() for d in res.skipped_days],
        "buy_limit_up": res.buy_limit_up,
        "unadjusted": res.unadjusted,
        "elapsed_ms": res.elapsed_ms,
        "hits": [
            {
                "trade_date": h.trade_date.isoformat(),
                "symbol": h.symbol,
                "entry_price": h.entry_price,
                "trigger_time": h.trigger_time,
                "score": h.score,
            }
            for h in res.hits
        ],
    }


async def _run_minute_replay(
    symbols: list[str],
    strategy_id: str,
    start: date,
    end: date,
    params: dict | None,
    registry: StrategyRegistry,
    progress_cb=None,
    cancel_event=None,
) -> dict:
    """分钟频策略回放管线（H2）：预拉日K 面板 + 分钟K，逐日回放策略出盘中命中。

    数据降级语义（与日K 回测一致）：任一环节失败/为空都返回结构完整的空结果，
    绝不抛错。日K 面板从 store 缓存直接读（调用方应先经 fetch 备数，缺失标的缺席）；
    分钟K 经 client_minute.get_minute_bars（带缓存 + 缺口补拉）。
    """
    from app.data.client_minute import get_minute_bars

    reg = registry or StrategyRegistry(_default_strategy_dirs())
    strategy = reg.get(strategy_id)
    empty = _minute_replay_result_dict(strategy_id, symbols, start, end, MinuteReplayResult())

    panel_start = _minute_panel_start(start, strategy.minute_daily_bars)
    daily: dict[str, pl.DataFrame] = {}
    for s in symbols:
        df = store.load(s)
        if df.is_empty():
            continue
        df = df.filter((pl.col("date") >= panel_start) & (pl.col("date") <= end))
        if not df.is_empty():
            daily[s] = df
    if not daily:
        logger.warning("分钟回放 %s：日线面板为空（store 无缓存），返回空结果", strategy_id)
        return empty

    try:
        minute = await get_minute_bars(sorted(daily), start, end, use_cache=True)
    except Exception as e:  # 分钟通路故障返回空结果（优雅降级）
        logger.warning("分钟回放 %s：分钟K 预拉失败，返回空结果：%s", strategy_id, e)
        return empty
    if not minute:
        logger.warning("分钟回放 %s：分钟K 为空，返回空结果", strategy_id)
        return empty

    fac = {s: factors.load(s) for s in daily}

    res = replay_minute_strategy(
        strategy, daily=daily, minute=minute, start=start, end=end,
        params=params, factors=fac, progress_cb=progress_cb, cancel_event=cancel_event,
    )
    return _minute_replay_result_dict(strategy_id, symbols, start, end, res)


def _build_minute_loader(
    cfg: MatcherConfig, minute_bars: dict[str, "pl.DataFrame"] | None
) -> MinuteLoader | None:
    """把预拉的分钟K 帧装配成 matcher 的 minute_loader。

    仅在分钟口径启用（minute_fill 或 exit_fill="signal_next_minute"）且有数据时
    返回加载器；否则返回 None（matcher 全程日K 口径）。加载器本身纯查表：
    按当日日期切片缓存，缺席返回 None（由 matcher 降级日K 口径）。
    """
    import numpy as np

    need = cfg.minute_fill or cfg.exit_fill == "signal_next_minute"
    if not need or not minute_bars:
        return None
    # 预索引：{symbol: {date: float64 2D 数组}}（只留数值列，datetime 用于分组）
    index: dict[str, dict[date, "np.ndarray"]] = {}
    for sym, df in minute_bars.items():
        if df is None or df.is_empty():
            continue
        day_map: dict[date, "np.ndarray"] = {}
        for day, part in df.group_by(df["datetime"].dt.date(), maintain_order=True):
            day_map[day[0]] = part.select(_MINUTE_COLS).to_numpy().astype(np.float64)
        if day_map:
            index[sym] = day_map
    if not index:
        return None
    return lambda sym, d: index.get(sym, {}).get(d)


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
    minute_bars: dict[str, "pl.DataFrame"] | None = None,
) -> dict:
    """跑一个策略在一组标的上的回测，返回统计 + 元信息。

    数据来自本地 Parquet 缓存（调用方应先经 fetch 备数；缺数标的在矩阵层降级为全 NaN 列）。
    benchmark / names 由 async 包装函数 run_backtest_async 预拉取传入（本函数保持同步）。
    names 缺省 None 时撮合按无名称（非 ST）分档，保持历史行为。
    minute_bars：{symbol: 分钟K DataFrame}（阶段 H1，由 run_backtest_async 预拉），
    仅 config.minute_fill 或 exit_fill="signal_next_minute" 时需要；缺省 None 时
    分钟口径整体降级日K（不抛错）。

    分钟频策略（META timeframes 含 "1m"）不走本函数（矩阵回测），
    由 run_backtest_async 分流到 _run_minute_replay（阶段 H2 回放路径）。
    若误以分钟策略调本同步入口，按「分钟数据不可用」优雅降级为分钟回放空结果。
    """
    reg = registry or StrategyRegistry(_default_strategy_dirs())
    sdef = reg.get(strategy_id)
    if sdef.is_minute_strategy:
        logger.warning(
            "分钟频策略 %s 需走异步入口 run_backtest_async（分钟K 预拉需协程）；"
            "同步入口降级为空分钟回放结果", strategy_id,
        )
        return _minute_replay_result_dict(strategy_id, symbols, start, end, MinuteReplayResult())

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
    # 分钟精确成交/盘中触发（阶段 H1）：把预拉的分钟K 帧装配成 matcher 的
    # minute_loader（symbol, date → float64 2D 数组），matcher 保持纯计算不做 IO。
    minute_loader = _build_minute_loader(cfg, minute_bars)
    result = simulate(
        adjusted_matrix,
        {s: signals.entry[:, j] for j, s in enumerate(adjusted_matrix.symbols)},
        {s: signals.exit[:, j] for j, s in enumerate(adjusted_matrix.symbols)},
        cfg,
        adjusted_flags=adjusted_flags,
        names=names,
        entry_refs=(
            {s: signals.entry_ref[:, j] for j, s in enumerate(adjusted_matrix.symbols)}
            if signals.entry_ref is not None else None
        ),
        exit_refs=(
            {s: signals.exit_ref[:, j] for j, s in enumerate(adjusted_matrix.symbols)}
            if signals.exit_ref is not None else None
        ),
        minute_loader=minute_loader,
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
            "entry_fill_mode": t.entry_fill_mode,
            "exit_fill_mode": t.exit_fill_mode,
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
        # 分钟成交覆盖统计（阶段 H1）：used=走分钟口径笔数，fallback=降级日K 笔数
        "minute_fill_used": result.minute_fill_used,
        "minute_fill_fallback": result.minute_fill_fallback,
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
    """async 包装：先拉基准/名称/分钟K（如需）再跑同步回测（HTTP API 用）。

    分钟K 预拉（阶段 H1）：config.minute_fill 或 exit_fill="signal_next_minute"
    时经 data/client_minute.get_minute_bars 拉全区间分钟K（带本地缓存）；
    拉取失败/为空时优雅降级（matcher 无 loader 走日K 口径）。

    分钟频策略分流（阶段 H2）：META timeframes 含 "1m" 的策略改走
    _run_minute_replay（逐日回放日线窗口 + 当日分钟流），不进矩阵回测路径。
    """
    reg = registry or StrategyRegistry(_default_strategy_dirs())
    if reg.get(strategy_id).is_minute_strategy:
        return await _run_minute_replay(symbols, strategy_id, start, end, params, reg)

    benchmark = await _fetch_benchmark(symbols, start, end)
    names = await _fetch_names(symbols)
    minute_bars: dict | None = None
    cfg = config or MatcherConfig()
    if cfg.minute_fill or cfg.exit_fill == "signal_next_minute":
        from app.data.client_minute import get_minute_bars
        try:
            minute_bars = await get_minute_bars(symbols, start, end, use_cache=True)
        except Exception as e:  # 分钟通路故障不阻塞回测，全程日K 口径降级
            logger.warning("分钟K 预拉失败，分钟口径降级日K：%s", e)
            minute_bars = None
    return run_backtest(
        symbols, strategy_id, start, end, params, config, reg, benchmark, names,
        minute_bars=minute_bars,
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
