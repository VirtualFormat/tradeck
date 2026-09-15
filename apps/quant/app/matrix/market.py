"""市场矩阵：从 Parquet 缓存构建「时间 × 标的」列存矩阵。

构建原则（回测正确性命门）：
- 全局交易日轴为所有标的交易日的并集（outer join），停牌/缺行一律 NaN，
  绝不把下一行数据错位接上。
- 价格口径为 daily_prices 原始价（adjust=none）；复权在 engine/adjust.py 做，这里不管。
- 矩阵只在内存构建，不做落盘缓存、多线程、懒加载（保持简单）。
- build_async（async 入口）：build 前先按需回源补拉缓存缺失标的
  （prod 容器缓存目录易随重建清空，只读缓存会全员全 NaN → 回测 0 成交）；
  build() 保持纯缓存读（cli / worker 子进程等同步调用方行为不变）。
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


async def build_async(
    symbols: list[str],
    start: date,
    end: date,
) -> MarketMatrix:
    """异步构建市场矩阵：缓存缺失标的先回源补拉落缓存，再按同步逻辑建矩阵。

    覆盖判定：区间内行数为 0 = 全缺；有数据但首尾日期盖不住 [start, end] = 部分缺
    （与 store.missing_ranges 同口径，区间内的停牌空洞不算缺）。
    有缺失标的时，经 client.fetch_bars 一次性批量补拉
    （自带分片分窗），逐标的 store.merge + store.save 落缓存，之后重新走 build()。
    「跳过回源」的语义由同步 build() 承担（纯缓存读），本函数始终按需回源。

    降级语义（与 build 一致，绝不抛错）：
    - 补拉请求整体失败 / 单个标的没补到数据：该标的保留全 NaN 列；
    - 只记日志，矩阵照常返回。

    注意：补拉只发生在主进程（HTTP API / CLI 的 async 入口）；worker 子进程
    只调同步 build() 读已暖好的缓存，不做网络 IO（与分钟K 预拉模式一致）。
    """
    from app.data import client

    syms = sorted(symbols)
    if not syms:
        return build(symbols, start, end)

    cached: dict[str, pl.DataFrame] = {}
    missing: list[str] = []
    for s in syms:
        df = store.load(s)
        if not df.is_empty():
            df = df.filter((pl.col("date") >= start) & (pl.col("date") <= end))
        cached[s] = df
        if (
            df.is_empty()
            or df["date"].min() > start
            or df["date"].max() < end
        ):
            missing.append(s)

    if not missing:
        logger.info("build_async：%d 只命中缓存，0 只回源补拉", len(syms))
        return build(symbols, start, end)

    try:
        bars = await client.fetch_bars(missing, start, end)
    except Exception as e:  # 网络/上游故障不阻塞构建，缺失标的全 NaN 降级
        logger.warning("build_async 补拉失败（%d 只标的按全 NaN 降级）：%s", len(missing), e)
        return build(symbols, start, end)

    # 按 symbol 分桶后逐标的 merge 落缓存（bars_to_frame 空列表返回空 schema 表）
    by_symbol: dict[str, list[dict]] = {s: [] for s in missing}
    for bar in bars:
        if bar.get("symbol") in by_symbol:
            by_symbol[bar["symbol"]].append(bar)
    filled = 0
    for s in missing:
        if not by_symbol[s]:
            continue  # 该标的区间内无数据（停牌/退市/上游缺数），保留全 NaN 列
        store.save(s, store.merge(store.load(s), store.bars_to_frame(by_symbol[s])))
        filled += 1

    failed = len(missing) - filled
    logger.info(
        "build_async：%d 只命中缓存，%d 只回源补拉（%d 只补拉无数据/失败）",
        len(syms) - len(missing), len(missing), failed,
    )
    return build(symbols, start, end)
