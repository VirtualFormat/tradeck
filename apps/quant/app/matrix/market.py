"""市场矩阵：从 Parquet 缓存构建「时间 × 标的」列存矩阵。

构建原则（回测正确性命门）：
- 全局交易日轴为所有标的交易日的并集（outer join），停牌/缺行一律 NaN，
  绝不把下一行数据错位接上。
- 价格口径为 daily_prices 原始价（adjust=none）；复权在 engine/adjust.py 做，这里不管。
- 矩阵只在内存构建，不做落盘缓存、多线程、懒加载（保持简单）。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

import numpy as np
import polars as pl

from app.data import store

logger = logging.getLogger(__name__)

# 矩阵字段（与 store._SCHEMA 的 OHLCV/amount 列一一对应）
FIELDS = ("open", "high", "low", "close", "volume", "amount")


@dataclass
class MarketMatrix:
    """市场矩阵：dates 为全局交易日轴（升序），symbols 为标的轴（升序）。

    每个字段一个 (len(dates), len(symbols)) 的 float64 二维数组，缺失为 NaN。
    """

    dates: list[date]
    symbols: list[str]
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray
    amount: np.ndarray

    @property
    def shape(self) -> tuple[int, int]:
        """（交易日数, 标的数）。"""
        return (len(self.dates), len(self.symbols))

    def slice(self, start: date | None = None, end: date | None = None) -> "MarketMatrix":
        """按日期区间切片（闭区间；None 表示该端不限制）。"""
        rows = [
            i
            for i, d in enumerate(self.dates)
            if (start is None or d >= start) and (end is None or d <= end)
        ]
        idx = np.array(rows, dtype=int)
        return MarketMatrix(
            dates=[self.dates[i] for i in rows],
            symbols=self.symbols,
            **{f: getattr(self, f)[idx] for f in FIELDS},
        )

    def select(self, symbols: list[str]) -> "MarketMatrix":
        """按标的子集选列（保持传入顺序；不存在的标的报 KeyError）。"""
        col_of = {s: j for j, s in enumerate(self.symbols)}
        missing = [s for s in symbols if s not in col_of]
        if missing:
            raise KeyError(f"矩阵中不存在的标的：{missing}")
        idx = np.array([col_of[s] for s in symbols], dtype=int)
        return MarketMatrix(
            dates=self.dates,
            symbols=list(symbols),
            **{f: getattr(self, f)[:, idx] for f in FIELDS},
        )


def build(symbols: list[str], start: date, end: date) -> MarketMatrix:
    """从 data 层 Parquet 缓存构建市场矩阵。

    逐标的读 store.load，过滤到 [start, end] 后 outer join 到全局交易日轴；
    缓存为空/损坏的标的保留为全 NaN 列（优雅降级，不抛错）。
    """
    syms = sorted(symbols)
    frames: list[pl.DataFrame] = []
    for s in syms:
        df = store.load(s)
        if not df.is_empty():
            # 防御性去重排序（store.save 已保证，重复 date 时后写胜出与 UPSERT 语义一致）
            df = (
                df.filter((pl.col("date") >= start) & (pl.col("date") <= end))
                .unique(subset=["date"], keep="last")
                .sort("date")
            )
        frames.append(df)

    # 全局交易日轴：所有标的交易日的并集，升序
    dates = sorted({d for df in frames for d in df["date"].to_list()})
    row_of = {d: i for i, d in enumerate(dates)}

    n_dates, n_syms = len(dates), len(syms)
    fields = {f: np.full((n_dates, n_syms), np.nan) for f in FIELDS}
    for j, df in enumerate(frames):
        if df.is_empty():
            logger.warning("标的 %s 缓存为空，矩阵对应列全为 NaN", syms[j])
            continue
        rows = np.array([row_of[d] for d in df["date"].to_list()], dtype=int)
        for f in FIELDS:
            # 统一转 float64：Int64 的 volume 含 null 时也能安全落进 NaN 矩阵
            fields[f][rows, j] = df[f].cast(pl.Float64).to_numpy()

    return MarketMatrix(dates=dates, symbols=syms, **fields)
