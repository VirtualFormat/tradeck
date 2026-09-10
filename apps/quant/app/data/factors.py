"""复权因子（data-api /api/factors → adjust_factors 表）— 回测动态复权的数据源。

原始价日K（adjust=none）× 因子在引擎内合成前复权序列（见 engine/adjust.py，阶段 B）。
qfq 为日频前复权因子（最新交易日 = 1.0，历史向最新价看齐，见
apps/data-collector/app/jobs/adjust_factors.py），与 ex_factor 缓存列语义兼容：
_factor_series 把因子对齐交易日轴后 factor[T_last]=1，engine 再除一次 1.0 为恒等。
因子缺失的标的降级为「无复权」并显式标注（优雅降级，不静默当已复权）。
注意：adjust_factors 表当前只有 A 股（CN）；US/HK 标的查询自然缺席 → 走降级
（unadjusted 标注），为预期行为，待因子源扩展到港美股后自动覆盖。
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from pathlib import Path

import polars as pl

from app.config import settings
from app.data import client

logger = logging.getLogger(__name__)

# 因子缓存列定义：date + ex_factor（落盘布局与下游 engine/adjust.py 的契约，不可改）
_SCHEMA = {"date": pl.Date, "ex_factor": pl.Float64}

# 无日期窗时的默认查询起点：A 股最早标的 1990 年上市，1980 足够兜底全历史
_DEFAULT_START = date(1980, 1, 1)


def _file_of(symbol: str) -> Path:
    return Path(settings.QUANT_CACHE_DIR) / "factors" / f"symbol={symbol}.parquet"


def load(symbol: str) -> pl.DataFrame:
    """读单标的因子缓存；不存在或损坏返回空表（= 无因子，调用方走降级）。"""
    path = _file_of(symbol)
    if not path.exists():
        return pl.DataFrame(schema=_SCHEMA)
    try:
        return pl.read_parquet(path)
    except Exception as e:
        logger.warning("因子缓存读取失败，按无因子处理（%s）：%s", path, e)
        return pl.DataFrame(schema=_SCHEMA)


async def fetch(
    symbols: list[str],
    start: date | None = None,
    end: date | None = None,
) -> dict[str, pl.DataFrame]:
    """批量拉复权因子并落缓存；返回 {symbol: DataFrame}，缺失标的缺席（降级）。

    start/end 默认 None = 全历史（拉因子通常要覆盖回测全区间）。
    data-api 返回缺某标的（无因子记录、或当前仅覆盖 A 股时的 US/HK 标的）→
    该标的缺席结果 + logger.info 标注，调用方按无复权处理。
    """
    rows = await client.fetch_factors(
        symbols,
        start or _DEFAULT_START,
        end or (date.today() + timedelta(days=1)),  # +1 天兜住含当日的未来除权预告
    )
    if not rows:
        logger.warning("/api/factors 返回空（%d 只标的均无因子或服务降级），按无复权降级", len(symbols))
        return {}

    by_symbol: dict[str, list[dict]] = {}
    for r in rows:
        if r.get("qfq") is None or r.get("date") is None:
            continue
        by_symbol.setdefault(r["symbol"], []).append(r)

    result: dict[str, pl.DataFrame] = {}
    for symbol, entries in by_symbol.items():
        df = pl.DataFrame(
            {
                "date": [date.fromisoformat(e["date"]) for e in entries],
                "ex_factor": [float(e["qfq"]) for e in entries],
            }
        ).sort("date")
        path = _file_of(symbol)
        path.parent.mkdir(parents=True, exist_ok=True)
        df.write_parquet(path)
        result[symbol] = df
    missing = set(symbols) - set(result)
    if missing:
        logger.info("复权因子缺失 %d 只（无因子记录或非 CN 市场），按无复权降级：%s",
                    len(missing), sorted(missing)[:5])
    return result
