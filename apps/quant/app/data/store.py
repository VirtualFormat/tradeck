"""Parquet 本地缓存 — quant 进程的行情缓存层（拉一次落盘复用，不重复打 API）。

布局：cache/daily/market=US/symbol=AAPL.parquet（按市场分目录）。
合并语义：按 date 去重，新数据胜出——与数据层 UPSERT 语义一致。
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import polars as pl

from app.config import settings

logger = logging.getLogger(__name__)

# daily_prices 的列定义（与 /api/bars 响应字段一致）
_SCHEMA = {
    "symbol": pl.String,
    "date": pl.Date,
    "open": pl.Float64,
    "high": pl.Float64,
    "low": pl.Float64,
    "close": pl.Float64,
    "volume": pl.Int64,
    "amount": pl.Float64,
}


def _market_of(symbol: str) -> str:
    """按规范 symbol 后缀判市场（与 backend markets.py 规则一致）。"""
    if symbol.endswith((".SH", ".SS", ".SZ", ".BJ")):
        return "CN"
    if symbol.endswith(".HK"):
        return "HK"
    return "US"


def _file_of(symbol: str) -> Path:
    return (
        Path(settings.QUANT_CACHE_DIR)
        / "daily"
        / f"market={_market_of(symbol)}"
        / f"symbol={symbol}.parquet"
    )


def load(symbol: str) -> pl.DataFrame:
    """读单标的缓存；不存在或损坏返回空表（降级，由调用方补拉重建）。"""
    path = _file_of(symbol)
    if not path.exists():
        return pl.DataFrame(schema=_SCHEMA)
    try:
        return pl.read_parquet(path)
    except Exception as e:  # 文件损坏：记日志当无缓存处理
        logger.warning("缓存读取失败，按无缓存处理（%s）：%s", path, e)
        return pl.DataFrame(schema=_SCHEMA)


def save(symbol: str, df: pl.DataFrame) -> None:
    """写单标的缓存（调用方保证 df 已按 date 排序去重）。"""
    path = _file_of(symbol)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(path)


def merge(existing: pl.DataFrame, new: pl.DataFrame) -> pl.DataFrame:
    """合并缓存与新拉数据：按 date 去重（新数据胜出），按 date 升序。"""
    if existing.is_empty():
        return new.sort("date")
    if new.is_empty():
        return existing.sort("date")
    return pl.concat([existing, new]).unique(subset=["date"], keep="last").sort("date")


def missing_ranges(cached: pl.DataFrame, start: date, end: date) -> list[tuple[date, date]]:
    """计算 [start, end] 中缓存未覆盖的区间（可能前后两段缺口）。

    以自然日近似：缓存 max 之后一律视为缺口；区间内的停牌空洞不补
    （日K 本身就没有非交易日行，补了也是空请求）。
    """
    if cached.is_empty():
        return [(start, end)]
    c_min, c_max = cached["date"].min(), cached["date"].max()
    ranges: list[tuple[date, date]] = []
    if start < c_min:
        ranges.append((start, min(end, c_min - timedelta(days=1))))
    if end > c_max:
        ranges.append((max(start, c_max + timedelta(days=1)), end))
    return ranges


def bars_to_frame(bars: list[dict[str, Any]]) -> pl.DataFrame:
    """/api/bars 响应行转 DataFrame（date 字符串转 Date 类型）。"""
    if not bars:
        return pl.DataFrame(schema=_SCHEMA)
    df = pl.DataFrame(bars)
    return df.with_columns(pl.col("date").str.to_date()).cast(_SCHEMA, strict=False)
