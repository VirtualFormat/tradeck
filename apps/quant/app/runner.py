"""回测管线 — 数据 → 矩阵 → 复权 → 策略 → 撮合 → 统计的最小闭环。

被 CLI run 与后续 HTTP API 共用：给定标的池 + 策略 + 区间，跑出统计结果。
每一环的降级都已内建：缺因子降级无复权标注、策略异常降级空信号、无交易返回全零骨架。
"""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

from app.data import factors, store
from app.engine import MatcherConfig, compute, forward_adjust, simulate
from app.matrix import build, enrich
from app.strategy import StrategyRegistry

logger = logging.getLogger(__name__)


def _default_strategy_dirs() -> dict[str, Path]:
    """三层策略目录：builtin 随包，custom/ai 在缓存卷（容器 /data/cache，本地 QUANT_CACHE_DIR）。"""
    from app.config import settings
    pkg_builtin = Path(__file__).resolve().parent / "strategy" / "builtin"
    cache = Path(settings.QUANT_CACHE_DIR) / "strategies"
    return {
        "builtin": pkg_builtin,
        "custom": cache / "custom",
        "ai": cache / "ai",
    }


def run_backtest(
    symbols: list[str],
    strategy_id: str,
    start: date,
    end: date,
    params: dict | None = None,
    config: MatcherConfig | None = None,
    registry: StrategyRegistry | None = None,
) -> dict:
    """跑一个策略在一组标的上的回测，返回统计 + 元信息。

    数据来自本地 Parquet 缓存（调用方应先经 fetch 备数；缺数标的在矩阵层降级为全 NaN 列）。
    """
    reg = registry or StrategyRegistry(_default_strategy_dirs())
    matrix = build(symbols, start, end)
    if not matrix.dates:
        logger.warning("区间 %s ~ %s 无缓存数据，返回空结果", start, end)
        return {"stats": compute_empty(), "strategy": strategy_id, "symbols": symbols,
                "range": [start.isoformat(), end.isoformat()], "unadjusted": symbols}

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
    )
    stats = compute(result)
    return {
        "stats": stats,
        "strategy": strategy_id,
        "symbols": symbols,
        "range": [matrix.dates[0].isoformat(), matrix.dates[-1].isoformat()],
        "unadjusted": result.unadjusted,
        "trades": len(result.trades),
    }


def compute_empty() -> dict:
    """无数据时的全零骨架（与 stats.compute 的空口径一致）。"""
    return {
        "total_return": 0.0, "annual_return": 0.0, "max_drawdown": 0.0,
        "annual_volatility": 0.0, "sharpe": 0.0, "calmar": 0.0,
        "trades": 0, "win_rate": 0.0, "profit_loss_ratio": 0.0,
        "turnover": 0.0, "days": 0, "final_value": 0.0, "unadjusted": [],
        "risk_free_rate": 0.0,
    }
