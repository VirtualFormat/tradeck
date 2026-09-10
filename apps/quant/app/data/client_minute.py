"""分钟K 数据通路 — 在线拉取（走 client.fetch_minute_bars）+ 按年 Parquet 缓存。

布局：{QUANT_CACHE_DIR}/minute/market=CN/symbol=600519.SH/year=2026.parquet
（与冷层基线 bars/minute 同构的分区风格，但属 quant 进程私有缓存，只写自己目录）。

语义对齐 data/store.py 日K缓存：
- 区间命中判定：请求区间 ⊆ 已缓存区间 → 直接读盘，零请求；
- 缺口补拉：只补缺段（分钟级数据按「自然日存在即视为覆盖」近似，与 store.missing_ranges 同理）；
- 合并去重：按 (symbol, datetime) 去重，新数据胜出——与 data-api UPSERT/去重语义一致。

三条铁律：本模块只走 data-api HTTP（client.py），绝不直连 DB/ClickHouse/冷层文件。
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import polars as pl

from app.config import settings
from app.data.client import fetch_minute_bars

logger = logging.getLogger(__name__)

# /api/bars/minute 响应列（与 apps/backend/app/api/minute_bars.py 输出字段一致）
_SCHEMA = {
    "symbol": pl.String,
    "datetime": pl.Datetime,
    "open": pl.Float64,
    "high": pl.Float64,
    "low": pl.Float64,
    "close": pl.Float64,
    "volume": pl.Float64,
    "amount": pl.Float64,
    "source": pl.String,
}


def _market_of(symbol: str) -> str:
    """按规范 symbol 后缀判市场（与 backend markets.py 规则一致；quant 包内唯一判定实现）。"""
    if symbol.endswith((".SH", ".SS", ".SZ", ".BJ")):
        return "CN"
    if symbol.endswith(".HK"):
        return "HK"
    return "US"


def _file_of(symbol: str, year: int) -> Path:
    return (
        Path(settings.QUANT_CACHE_DIR)
        / "minute"
        / f"market={_market_of(symbol)}"
        / f"symbol={symbol}"
        / f"year={year}.parquet"
    )


def load_minute(symbol: str, year: int) -> pl.DataFrame:
    """读单标的单年缓存；不存在或损坏返回空表（降级，由调用方补拉重建）。"""
    path = _file_of(symbol, year)
    if not path.exists():
        return pl.DataFrame(schema=_SCHEMA)
    try:
        return pl.read_parquet(path)
    except Exception as e:  # 文件损坏：记日志当无缓存处理
        logger.warning("分钟缓存读取失败，按无缓存处理（%s）：%s", path, e)
        return pl.DataFrame(schema=_SCHEMA)


def save_minute(symbol: str, year: int, df: pl.DataFrame) -> None:
    """写单标的单年缓存（调用方保证 df 已按 datetime 排序去重）。"""
    path = _file_of(symbol, year)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(path)


def merge_minute(existing: pl.DataFrame, new: pl.DataFrame) -> pl.DataFrame:
    """合并缓存与新拉数据：按 (symbol, datetime) 去重（新数据胜出），按 datetime 升序。"""
    if existing.is_empty():
        return new.sort("datetime")
    if new.is_empty():
        return existing.sort("datetime")
    return (
        pl.concat([existing, new])
        .unique(subset=["symbol", "datetime"], keep="last")
        .sort("datetime")
    )


def missing_minute_ranges(
    cached: pl.DataFrame, start: date, end: date
) -> list[tuple[date, date]]:
    """计算 [start, end] 中缓存未覆盖的区间（可能前后两段缺口）。

    以自然日近似：缓存 datetime 的 min/max 之间一律视为已覆盖；
    区间内盘前/休市空洞不补（分钟K 本身就没有非交易时段行，补了也是空请求）。
    """
    if cached.is_empty():
        return [(start, end)]
    c_min = cached["datetime"].min().date()
    c_max = cached["datetime"].max().date()
    ranges: list[tuple[date, date]] = []
    if start < c_min:
        ranges.append((start, min(end, c_min - timedelta(days=1))))
    if end > c_max:
        ranges.append((max(start, c_max + timedelta(days=1)), end))
    return ranges


def minute_bars_to_frame(bars: list[dict[str, Any]]) -> pl.DataFrame:
    """/api/bars/minute 响应行转 DataFrame（datetime ISO 字符串转 Datetime 类型）。"""
    if not bars:
        return pl.DataFrame(schema=_SCHEMA)
    df = pl.DataFrame(bars)
    return df.with_columns(pl.col("datetime").str.to_datetime()).cast(_SCHEMA, strict=False)


def _years_in(start: date, end: date) -> range:
    return range(start.year, end.year + 1)


async def get_minute_bars(
    symbols: list[str],
    start: date,
    end: date,
    *,
    use_cache: bool = True,
) -> dict[str, pl.DataFrame]:
    """带缓存的分钟K 入口：区间命中直接读盘，缺口补拉后合并落盘。

    返回 {symbol: DataFrame}；拉取失败的标的缺席（降级，不抛错）。
    按年分片读写缓存；跨年请求自动拆成各年文件处理。
    逐标的串行 await（与 fetch 降级语义一致）；大 symbols 列表的并发编排
    由上层（H 阶段回测）决定，这里保持实现简单。
    """
    result: dict[str, pl.DataFrame] = {}
    for symbol in symbols:
        frames: list[pl.DataFrame] = []
        for year in _years_in(start, end):
            y_start = max(start, date(year, 1, 1))
            y_end = min(end, date(year, 12, 31))
            cached = load_minute(symbol, year) if use_cache else pl.DataFrame(schema=_SCHEMA)
            ranges = missing_minute_ranges(cached, y_start, y_end)
            new_df = pl.DataFrame(schema=_SCHEMA)
            for r_start, r_end in ranges:
                bars = await fetch_minute_bars([symbol], r_start, r_end)
                if not bars:
                    logger.warning("分钟K 缺口补拉无数据（%s，%s ~ %s）", symbol, r_start, r_end)
                    continue
                new_df = merge_minute(new_df, minute_bars_to_frame(bars))
            if ranges:
                merged = merge_minute(cached, new_df)
                if not merged.is_empty():
                    save_minute(symbol, year, merged)
                cached = merged
            if cached.is_empty():
                continue
            # 只截取请求区间内的行（缓存可能覆盖更大范围）
            frames.append(
                cached.filter(
                    (pl.col("datetime") >= pl.lit(y_start).cast(pl.Datetime))
                    & (pl.col("datetime") < pl.lit(y_end + timedelta(days=1)).cast(pl.Datetime))
                )
            )
        if frames:
            result[symbol] = pl.concat(frames).sort("datetime")
    return result


def get_minute_bars_sync(
    symbols: list[str],
    start: date,
    end: date,
    *,
    use_cache: bool = True,
) -> dict[str, pl.DataFrame]:
    """get_minute_bars 的同步包装（供 CLI/回测主流程在非协程上下文调用）。"""
    return asyncio.run(get_minute_bars(symbols, start, end, use_cache=use_cache))
