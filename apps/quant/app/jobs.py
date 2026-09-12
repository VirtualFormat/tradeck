"""每日信号扫描 job — 对 universe 跑已发布/内置策略，信号落 Parquet 供 web 展示。

纪律（与数据层一致）：
- quant 无 DB（单一写者铁律：DB 只有 collector 写），信号写 quant-cache Parquet。
- universe 默认 DEFAULT_SIGNAL_UNIVERSE（沿用数据层 tracked 100 只的定义；
  quant 单 app 不能 import data-collector，这里内联同源拷贝）；
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

# 默认 universe：回测/选股 API 在 symbols 为空时的默认标的池（"tracked" 档位，
# 见 app/universe.py），同时作为每日信号 job 的默认 universe。
# 与 data-collector app/constants.py TRACKED_SYMBOLS 同源拷贝
#（quant 是独立 app，跨 app import 违反边界；collector 侧若调整需同步这里）。
DEFAULT_SIGNAL_UNIVERSE: list[str] = [
    # ── 美股科技（30）──
    "AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "GOOGL", "META", "NFLX",
    "AMD", "INTC", "AVGO", "QCOM", "ADBE", "CRM", "ORCL", "CSCO",
    "ACN", "IBM", "NOW", "UBER", "LYFT", "SNAP", "PINS", "SHOP",
    "XYZ", "PYPL", "COIN", "PLTR", "SNOW", "ZM",
    # ── 美股金融/消费/医疗（20）──
    "JPM", "BAC", "WFC", "GS", "MS", "C", "BLK", "V", "MA", "AXP",
    "WMT", "COST", "HD", "MCD", "NKE", "SBUX", "DIS", "KO", "PEP", "PG",
    # ── 美股能源/工业（10）──
    "XOM", "CVX", "COP", "SLB", "EOG", "BA", "CAT", "GE", "HON", "UPS",
    # ── A 股（30）──（沪市用 .SH，与 TickFlow/业界一致）
    "600519.SH", "601318.SH", "600036.SH", "000858.SZ", "002594.SZ",
    "300750.SZ", "601012.SH", "600900.SH", "000001.SZ", "601166.SH",
    "600276.SH", "601398.SH", "000333.SZ", "600030.SH", "601888.SH",
    "600031.SH", "000651.SZ", "002415.SZ", "300059.SZ", "600009.SH",
    "601628.SH", "600585.SH", "000568.SZ", "002714.SZ", "600436.SH",
    "603259.SH", "601857.SH", "600028.SH", "601088.SH", "600019.SH",
    # ── 港股（10）──（5 位补零，与 TickFlow/业界一致）
    "00700.HK", "09988.HK", "01810.HK", "03690.HK", "09618.HK",
    "00005.HK", "01299.HK", "00883.HK", "00939.HK", "02318.HK",
]


def signal_universe() -> list[str]:
    """解析每日信号 universe：QUANT_SIGNAL_UNIVERSE 非空时按逗号切分，否则用默认子集。"""
    raw = settings.QUANT_SIGNAL_UNIVERSE.strip()
    if not raw:
        return list(DEFAULT_SIGNAL_UNIVERSE)
    return [s.strip() for s in raw.split(",") if s.strip()]


_SIGNALS_SCHEMA = {
    "date": pl.Date, "strategy_id": pl.String, "symbol": pl.String,
    "score": pl.Float64, "entry": pl.Boolean, "exit": pl.Boolean, "market": pl.String,
}


async def daily_signals_job() -> int:
    """每日信号定时任务入口（模块级 async def，已知坑#7：APScheduler 只接协程函数）。

    优雅降级：任何失败只记日志返回 0，不向上抛（调度器/API 均不受影响）。
    """
    try:
        symbols = signal_universe()
        n = run_daily_signals(symbols, user_id=settings.QUANT_DEFAULT_USER)
        logger.info("每日信号 job done: %d rows（universe=%d，user=%s）",
                    n, len(symbols), settings.QUANT_DEFAULT_USER)
        return n
    except Exception as e:
        logger.error("每日信号 job 失败（不影响 API，下次 cron 重试）：%s", e)
        return 0


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
