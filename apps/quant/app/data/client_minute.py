"""分钟K 数据通路 — 在线拉取（走 client.fetch_minute_bars）+ 按年 Parquet 缓存。

布局：{QUANT_CACHE_DIR}/minute/market=CN/symbol=600519.SH/year=2026.parquet
（与冷层基线 bars/minute 同构的分区风格，但属 quant 进程私有缓存，只写自己目录）。

语义对齐 data/store.py 日K缓存：
- 覆盖账本嵌入 Parquet 元数据，逐日记录成功且未截断的查询；
- 旧缓存保留数据，缺账本时按未验证处理，空日期作短期负缓存；
- 合并去重：按 (symbol, datetime) 去重，新数据胜出——与 data-api UPSERT/去重语义一致。

三条铁律：本模块只走 data-api HTTP（client.py），绝不直连 DB/ClickHouse/冷层文件。
"""

from __future__ import annotations

import asyncio
import logging
import os
import stat
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl
import pyarrow.parquet as pq

from app.config import settings
from app.data.client import fetch_minute_bars_with_coverage
from app.data.minute_coverage import (
    dates,
    decode_coverage,
    encode_coverage,
    locked_cache,
    locked_cache_sync,
    missing_ranges,
    utc_today,
)

logger = logging.getLogger(__name__)

_FETCH_TIMEOUT_SECONDS = 180.0

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


def _load_minute_state(symbol: str, year: int) -> tuple[pl.DataFrame, set[date]]:
    """从同一 Parquet 快照读取数据与账本，旧文件只提供数据。"""
    path = _file_of(symbol, year)
    if not path.exists():
        return pl.DataFrame(schema=_SCHEMA), set()
    try:
        with pq.ParquetFile(path) as parquet:
            df = pl.from_arrow(parquet.read()).select(list(_SCHEMA)).cast(_SCHEMA)
            metadata = parquet.metadata.metadata or {}
    except Exception as exc:
        logger.warning(
            "分钟缓存读取失败，按无缓存处理（%s）：%s", path, type(exc).__name__
        )
        return pl.DataFrame(schema=_SCHEMA), set()
    try:
        covered = decode_coverage(metadata, year)
    except (ValueError, TypeError, AttributeError) as exc:
        logger.warning("分钟覆盖账本读取失败（%s）：%s", path, type(exc).__name__)
        covered = set()
    return df, covered


def load_minute(symbol: str, year: int) -> pl.DataFrame:
    """兼容入口：读取旧/新单年缓存，损坏时返回空表。"""
    return _load_minute_state(symbol, year)[0]


def _write_minute(symbol: str, year: int, df: pl.DataFrame, covered: set[date]) -> None:
    """调用方持有文件锁；数据与覆盖一次原子发布，失败保留完整旧版本。"""
    path = _file_of(symbol, year)
    path.parent.mkdir(parents=True, exist_ok=True)
    present = set(df["datetime"].dt.date().to_list())
    table = df.to_arrow().replace_schema_metadata(
        encode_coverage(covered, covered - present)
    )
    fd, name = tempfile.mkstemp(
        prefix=f"{path.name}.tmp.{os.getpid()}.", dir=path.parent
    )
    tmp = Path(name)
    try:
        # 保留旧文件权限，新文件沿用原写法的可读模式，降权 worker 仍可读取。
        mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644
        os.fchmod(fd, mode)
        os.close(fd)
        fd = -1
        pq.write_table(table, tmp, compression="zstd")
        with tmp.open("rb") as file:
            os.fsync(file.fileno())
        os.replace(tmp, path)
    finally:
        if fd >= 0:
            os.close(fd)
        tmp.unlink(missing_ok=True)


def save_minute(symbol: str, year: int, df: pl.DataFrame) -> None:
    """兼容独立写入口：任意外部写入不继承覆盖证明，原子替换文件。"""
    with locked_cache_sync(_file_of(symbol, year)):
        _write_minute(symbol, year, df, set())


def merge_minute(existing: pl.DataFrame, new: pl.DataFrame) -> pl.DataFrame:
    """合并缓存与新拉数据：按 (symbol, datetime) 去重（新数据胜出），按 datetime 升序。"""
    return (
        pl.concat([existing, new])
        .unique(subset=["symbol", "datetime"], keep="last")
        .sort(["symbol", "datetime"])
    )


def missing_minute_ranges(
    cached: pl.DataFrame, start: date, end: date, *, covered: set[date] | None = None
) -> list[tuple[date, date]]:
    """旧签名兼容；只有显式账本可证明覆盖，行的 min/max 不作为证据。"""
    return missing_ranges(covered or set(), start, end)


def minute_bars_to_frame(bars: list[dict[str, Any]]) -> pl.DataFrame:
    """/api/bars/minute 响应行转 DataFrame（datetime ISO 字符串转 Datetime 类型）。"""
    if not bars:
        return pl.DataFrame(schema=_SCHEMA)
    df = pl.DataFrame(bars)
    return (
        df.select(list(_SCHEMA))
        .with_columns(pl.col("datetime").str.to_datetime())
        .cast(_SCHEMA, strict=False)
    )


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

    返回 {symbol: DataFrame}；失败时保留请求范围内已有行，无可用行则标的缺席。
    账本只证明请求成功且未截断，无法证明服务端行情逐分钟齐全。
    按年分片读写缓存；跨年请求自动拆成各年文件处理。
    逐标的串行 await（与 fetch 降级语义一致）；大 symbols 列表的并发编排
    由上层（H 阶段回测）决定，这里保持实现简单。
    """
    result: dict[str, pl.DataFrame] = {}
    if end < start:
        return result
    for symbol in sorted(set(symbols)):
        frames: list[pl.DataFrame] = []
        for year in _years_in(start, end):
            y_start = max(start, date(year, 1, 1))
            y_end = min(end, date(year, 12, 31))
            try:
                async with locked_cache(_file_of(symbol, year)):
                    cached, covered = _load_minute_state(symbol, year)
                    ranges = missing_minute_ranges(
                        cached, y_start, y_end, covered=covered
                    )
                    if not use_cache:
                        ranges = [(y_start, y_end)]
                    new_df = pl.DataFrame(schema=_SCHEMA)
                    changed = False
                    for r_start, r_end in ranges:
                        # 重新验证范围一旦失败，旧证明也不能继续沿用。
                        invalidated = covered.intersection(dates(r_start, r_end))
                        covered.difference_update(invalidated)
                        if invalidated:
                            # 先发布旧数据与撤销后的账本，再发请求，进程退出也能安全重试。
                            _write_minute(symbol, year, cached, covered)
                        try:
                            fetched = await asyncio.wait_for(
                                fetch_minute_bars_with_coverage(
                                    [symbol], r_start, r_end
                                ),
                                timeout=_FETCH_TIMEOUT_SECONDS,
                            )
                        except TimeoutError:
                            logger.warning(
                                "分钟K 窗口读取超时（%s，%s ~ %s）",
                                symbol,
                                r_start,
                                r_end,
                            )
                            continue
                        try:
                            fresh = minute_bars_to_frame(fetched.bars)
                        except (
                            pl.exceptions.PolarsError,
                            ValueError,
                            TypeError,
                        ) as exc:
                            logger.warning(
                                "分钟K 行转换失败（%s）：%s", symbol, type(exc).__name__
                            )
                            continue
                        new_df = merge_minute(new_df, fresh)
                        for c_start, c_end in fetched.covered_ranges.get(symbol, []):
                            # 当日/未来数据仍可能变化，下次继续回源。
                            verified = {
                                day
                                for day in dates(c_start, c_end)
                                if day < utc_today()
                            }
                            covered.update(verified)
                            # 成功子窗完整替换旧键，包含已确认的空响应。
                            cached = cached.filter(
                                ~pl.col("datetime").dt.date().is_between(c_start, c_end)
                            )
                            changed = True
                        changed = changed or not fresh.is_empty()
                    merged = merge_minute(cached, new_df)
                    if changed:
                        try:
                            _write_minute(symbol, year, merged, covered)
                        except Exception as exc:
                            logger.warning(
                                "分钟缓存写入失败（%s）：%s", symbol, type(exc).__name__
                            )
                    # bypass 仍落盘更新，但本次只返回回源行，保持原接口语义。
                    returned = merged if use_cache else new_df
            except (OSError, TimeoutError) as exc:
                logger.warning(
                    "分钟缓存锁或账本更新失败（%s）：%s", symbol, type(exc).__name__
                )
                returned = (
                    load_minute(symbol, year)
                    if use_cache
                    else pl.DataFrame(schema=_SCHEMA)
                )
            frame = returned.filter(
                pl.col("datetime").dt.date().is_between(y_start, y_end)
            )
            if not frame.is_empty():
                frames.append(frame)
        if frames:
            result[symbol] = pl.concat(frames).sort(["symbol", "datetime"])
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
