"""每日信号扫描 job — 对 universe 跑已发布/内置策略，信号落 Parquet 供 web 展示。

纪律（与数据层一致）：
- quant 无 DB（单一写者铁律：DB 只有 collector 写），信号写 quant-cache Parquet。
- universe 默认 tracked 标的（沿用数据层 100 只的定义，经 data-api 读）；
  也可经 QUANT_SIGNAL_UNIVERSE 环境变量覆盖（逗号分隔）。
- 优雅降级：单策略/单标的失败只记日志，不中断整轮。
"""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import polars as pl

from app.config import settings
from app.runner import user_strategy_dirs
from app.screener import screen
from app.strategy import StrategyRegistry

logger = logging.getLogger(__name__)

_SIGNALS_SCHEMA = {
    "date": pl.Date, "strategy_id": pl.String, "symbol": pl.String,
    "score": pl.Float64, "entry": pl.Boolean, "exit": pl.Boolean, "market": pl.String,
}


def _signals_file(user_id: str | None = None) -> Path:
    """信号快照路径（多用户骨架 G4：用户命名空间隔离，缺省回落 QUANT_DEFAULT_USER）。"""
    uid = user_id or settings.QUANT_DEFAULT_USER
    return Path(settings.QUANT_CACHE_DIR) / "users" / uid / "signals" / "latest.parquet"


def load_signals(user_id: str | None = None) -> pl.DataFrame:
    """读最新信号表（web 展示用）；不存在或损坏返回空表。"""
    f = _signals_file(user_id)
    if not f.exists():
        return pl.DataFrame(schema=_SIGNALS_SCHEMA)
    try:
        return pl.read_parquet(f)
    except Exception as e:
        logger.warning("信号表读取失败：%s", e)
        return pl.DataFrame(schema=_SIGNALS_SCHEMA)


def run_daily_signals(
    symbols: list[str], strategy_ids: list[str] | None = None,
    user_id: str | None = None,
) -> int:
    """对 universe 跑策略，把当日 entry 信号写信号表（覆盖式最新快照）。返回写入行数。"""
    reg = StrategyRegistry(user_strategy_dirs(user_id))
    ids = strategy_ids or [s.strategy_id for s in reg.all()]
    rows = []
    today = date.today()
    for sid in ids:
        try:
            res = screen(sid, symbols, registry=reg)
        except Exception as e:
            logger.warning("策略 %s 信号扫描失败，跳过：%s", sid, e)
            continue
        for r in res.rows:
            if r.signals.get("entry"):
                rows.append({
                    "date": today, "strategy_id": sid, "symbol": r.symbol,
                    "score": r.score, "entry": True, "exit": bool(r.signals.get("exit")),
                    "market": r.market,
                })
    df = pl.DataFrame(rows, schema=_SIGNALS_SCHEMA) if rows else pl.DataFrame(schema=_SIGNALS_SCHEMA)
    f = _signals_file(user_id)
    f.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(f)
    logger.info("每日信号扫描完成：%d 策略 × %d 标的 → %d 条信号", len(ids), len(symbols), df.height)
    return df.height
