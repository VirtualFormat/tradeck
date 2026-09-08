"""同花顺 Market Dumps 导入 job：全市场 A 股日K → PG（CN 日K 主源）。

链路：签名 URL → 流式下载落盘缓存 → pyarrow 分批解析 → PG UPSERT +
自有年度 Parquet。增量 dump 不可用时，仅用 findb 补 tracked A 股，避免
单-code API 全市场扫描触发 429。

全量 daily-k 约 945 万行/170MB。两个关键设计（小内存 prod 机 7.5GB 必备）：
- **下载落盘缓存**：先存容器本地文件，已下载且未过期直接复用，进程重启/导入
  失败不重复下载（11 分钟慢速下一次成功，重跑秒过）；导入成功后删除。
- **分批解析**：pyarrow iter_batches 按 _PARSE_BATCH 行流式读，配合分批 UPSERT，
  内存占用恒定（~几百 MB），绝不 to_pylist() 全量进内存。

dump 类型（契约见 Financial-API/docs/api/endpoints-market-dumps.md）：
- daily-k-10d：全市场近 10 交易日（~5.5 万行/1MB）——每日增量主源
  （cron 挂在 scheduler `_daily_kline_cn_hk`，A 股盘后 08:30 UTC）
- daily-k：全市场约 10 年（~945 万行/170MB）——首次全量初始化
  （启动缺口自动检测 / 手动触发）
- adjustment-factors：全市场复权事件（分红/送股/配股）——事件流而非 findb
  的日频 qfq/hfq 因子，本 job 不落 adjust_factors；日频因子仍由 findb 维护。

复权口径：dump 日K 为原始未复权价（adjusted=none），与 daily_prices 现有
「存原始价 + 复权因子」体系一致，UPSERT 与 TickFlow 日K 互为同源覆盖。

纪律：单一写者（仅 collector 写）、UPSERT 幂等（(symbol,date) 冲突覆盖）、
优雅降级（未配置 key / 下载失败 / 解析失败记日志返回 0，不抛错）。
"""
from __future__ import annotations

import asyncio
import logging
import os
import tempfile
import time
from datetime import date, datetime, timezone, timedelta
from typing import Any

import httpx

from app.datasource import hithink_source
from app.datasource import findb_source
from app.config import settings
from app.constants import TRACKED_SYMBOLS
from app.db import get_pool
from app.quality import quality_gate

logger = logging.getLogger(__name__)

# 分批 UPSERT 单批行数（写库）
_UPSERT_BATCH = 20_000
# pyarrow 分批解析单批行数（读 Parquet）
_PARSE_BATCH = 20_000
# 全量 Parquet 本地缓存有效期（秒）：>24h 视为过期重新下载
_DUMP_CACHE_TTL = 24 * 3600

_TZ_CN = timezone(timedelta(hours=8))

# merge_daily_pool 的文件级并发锁：key 为 target Parquet 路径。
# 同一 (year, market) 文件的 merge 串行化，防并发 read_parquet/os.replace 竞态。
_MERGE_FILE_LOCKS: dict[str, asyncio.Lock] = {}


def _ms_to_date(ms: Any) -> date | None:
    """Asia/Shanghai 零点毫秒戳 → date。"""
    try:
        return datetime.fromtimestamp(int(ms) / 1000, tz=_TZ_CN).date()
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _to_float(x: Any) -> float | None:
    if x is None:
        return None
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return None if f != f else f  # NaN → None


def _to_int(x: Any) -> int | None:
    f = _to_float(x)
    return None if f is None else int(f)


def _cache_path(dump_type: str) -> str:
    return os.path.join(tempfile.gettempdir(), f"hithink_dump_{dump_type}.parquet")


def _pool_daily_path(year: int, market: str = "CN") -> str:
    return os.path.join(
        settings.DATA_POOL_ROOT,
        "bars",
        "daily",
        "asset=stock",
        f"market={market}",
        f"year={year}.parquet",
    )


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def merge_daily_baseline(source: str, target: str, market: str) -> None:
    """把 findb 历史基线并入已存在的增量分片，保留历史扩展字段。

    同日期以自有增量 OHLCVA/source 为准；PE/PB/市值等仅历史源提供的列继续
    保留，避免初始化顺序导致当年基线被近 10 日增量遮蔽。
    """
    import duckdb

    temporary = f"{target}.baseline.part"
    connection = duckdb.connect()
    try:
        existing_columns = [
            row[0]
            for row in connection.execute(
                "DESCRIBE SELECT * FROM read_parquet(?,hive_partitioning=false)",
                [target],
            ).fetchall()
        ]
        baseline_columns = [
            row[0]
            for row in connection.execute(
                "DESCRIBE SELECT * FROM read_parquet(?,hive_partitioning=false)",
                [source],
            ).fetchall()
        ]
        preferred = [
            "symbol", "market", "date", "open", "high", "low", "close",
            "volume", "amount", "source",
        ]
        output_columns = preferred + [
            column
            for column in baseline_columns + existing_columns
            if column not in preferred
        ]
        output_columns = list(dict.fromkeys(output_columns))
        expressions = []
        for column in output_columns:
            existing = f'e."{column}"' if column in existing_columns else "NULL"
            baseline = f'b."{column}"' if column in baseline_columns else "NULL"
            if column == "market":
                expressions.append(
                    f"COALESCE({existing},{baseline},'{market}') AS market"
                )
            else:
                expressions.append(
                    f'COALESCE({existing},{baseline}) AS "{column}"'
                )
        connection.execute(
            f"""
            COPY (
                SELECT {', '.join(expressions)}
                FROM read_parquet(
                    {_sql_literal(target)}, hive_partitioning=false
                ) e
                FULL OUTER JOIN read_parquet(
                    {_sql_literal(source)}, hive_partitioning=false
                ) b USING (symbol,date)
                ORDER BY symbol,date
            ) TO {_sql_literal(temporary)}
            (FORMAT PARQUET,COMPRESSION ZSTD,ROW_GROUP_SIZE 122880)
            """
        )
        os.replace(temporary, target)
    finally:
        connection.close()
        if os.path.exists(temporary):
            os.remove(temporary)


async def merge_daily_pool(
    records: list[tuple], *, source: str, market: str
) -> int:
    """把标准化日K合并进自有 Parquet data pool（按 symbol/date 幂等）。"""
    if not records:
        return 0

    # 并发竞态修复（2026-09-08）：daily_kline 对同一 market 的不同 symbol 批次
    # 会并发调本函数，它们写同一个 (year, market) Parquet 文件——一个 merge 在
    # os.replace 替换文件、另一个正在 read_parquet，会读到替换到一半的文件，
    # 报 _duckdb.Error: TProtocolException: Invalid data。按 target 文件路径加
    # 进程级 asyncio.Lock，同一文件的 merge 串行化；不同 (year, market) 文件
    # 仍可并发（不牺牲吞吐）。参考 app/api/ondemand.py 的 per-key 锁模式。

    def merge(year: int, year_records: list[tuple]) -> int:
        import duckdb

        target = _pool_daily_path(year, market)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        temporary = f"{target}.part"
        connection = duckdb.connect()
        try:
            connection.execute(
                """
                CREATE TABLE incoming (
                    symbol VARCHAR, market VARCHAR, date DATE,
                    open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE,
                    volume BIGINT, amount DOUBLE, source VARCHAR
                )
                """
            )
            connection.executemany(
                "INSERT INTO incoming VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [(*row, source) for row in year_records],
            )
            target_sql = _sql_literal(target)
            temporary_sql = _sql_literal(temporary)
            if os.path.exists(target):
                existing_columns = [
                    row[0]
                    for row in connection.execute(
                        "DESCRIBE SELECT * FROM read_parquet(?,hive_partitioning=false)",
                        [target],
                    ).fetchall()
                ]
                core_columns = [
                    "symbol", "market", "date", "open", "high", "low", "close",
                    "volume", "amount", "source",
                ]
                output_columns = core_columns + [
                    column
                    for column in existing_columns
                    if column not in core_columns
                ]
                expressions = []
                for column in output_columns:
                    if column in core_columns:
                        existing = (
                            f'e."{column}"'
                            if column in existing_columns
                            else "NULL"
                        )
                        if column == "market":
                            expressions.append(
                                f"COALESCE(i.market,{existing},'{market}') AS market"
                            )
                        else:
                            expressions.append(
                                f'COALESCE(i."{column}",{existing}) AS "{column}"'
                            )
                    else:
                        expressions.append(f'e."{column}"')
                query = f"""
                    SELECT {', '.join(expressions)}
                    FROM read_parquet(
                        {target_sql}, union_by_name=true, hive_partitioning=false
                    ) e
                    FULL OUTER JOIN incoming i USING (symbol,date)
                    ORDER BY symbol,date
                """
                connection.execute(
                    f"COPY ({query}) TO {temporary_sql} "
                    "(FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 122880)"
                )
            else:
                connection.execute(
                    f"""
                    COPY (
                        SELECT * FROM incoming ORDER BY symbol, date
                    ) TO {temporary_sql}
                    (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 122880)
                    """
                )
            os.replace(temporary, target)
            return connection.execute("SELECT count(*) FROM incoming").fetchone()[0]
        finally:
            connection.close()
            if os.path.exists(temporary):
                os.remove(temporary)

    by_year: dict[int, list[tuple]] = {}
    for row in records:
        by_year.setdefault(row[2].year, []).append(row)
    total = 0
    for year, year_records in sorted(by_year.items()):
        target = _pool_daily_path(year, market)
        lock = _MERGE_FILE_LOCKS.setdefault(target, asyncio.Lock())
        async with lock:
            total += await asyncio.to_thread(merge, year, year_records)
    return total


async def _ensure_dump_file(dump_type: str, *, full: bool) -> str | None:
    """确保本地有 dump Parquet 文件：缓存有效直接复用，否则流式下载落盘。

    返回文件路径；下载失败/未配置 key 返回 None。
    """
    path = _cache_path(dump_type)
    # 缓存复用：文件存在且未过期（全量 170MB 慢速下，避免重启重复下载）
    if os.path.exists(path):
        age = time.time() - os.path.getmtime(path)
        if age < _DUMP_CACHE_TTL and os.path.getsize(path) > 0:
            logger.info(
                "复用本地缓存 dump %s（%.1f MB，%d 分钟前下载）",
                dump_type, os.path.getsize(path) / 1024 / 1024, int(age / 60),
            )
            return path
        os.remove(path)  # 过期删了重下

    url = await hithink_source.get_dump_download_url(dump_type)
    if not url:
        return None

    logger.info("流式下载 dump %s → %s", dump_type, path)
    timeout = 1800.0 if full else 180.0  # 全量 170MB 慢速留足
    tmp = f"{path}.part"
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(timeout, read=timeout), follow_redirects=True
        ) as client:
            async with client.stream("GET", url) as res:
                if res.status_code != 200:
                    logger.warning("同花顺 dump 下载失败 %s: HTTP %s", dump_type, res.status_code)
                    return None
                with open(tmp, "wb") as f:
                    async for chunk in res.aiter_bytes(1024 * 512):
                        f.write(chunk)
        os.replace(tmp, path)  # 下完原子改名，避免半截文件被当缓存
        logger.info(
            "dump %s 下载完成：%.1f MB", dump_type, os.path.getsize(path) / 1024 / 1024
        )
        return path
    except (httpx.HTTPError, OSError) as e:
        logger.warning("同花顺 dump 下载异常 %s: %s", dump_type, e)
        for p in (tmp,):
            if os.path.exists(p):
                os.remove(p)
        return None


async def _upsert_batch(conn: Any, records: list[tuple]) -> None:
    """单批 UPSERT daily_prices。"""
    await conn.executemany(
        """
        INSERT INTO daily_prices
            (symbol, market, date, open, high, low, close, volume, amount)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
        ON CONFLICT (symbol, date) DO UPDATE SET
            open = EXCLUDED.open, high = EXCLUDED.high,
            low = EXCLUDED.low, close = EXCLUDED.close,
            volume = EXCLUDED.volume,
            amount = EXCLUDED.amount
        """,
        records,
    )


async def _run_findb_tracked_fallback() -> int:
    """同花顺增量不可用时，仅补 tracked A 股。

    findb bars 是单标的接口，不能在 fallback 中扫描 5500+ 全市场（会触发
    429 且耗时过长）。这里串行补 30 只 tracked A 股，保证看板不断流；
    全市场缺口留待下一次同花顺 10d dump 自动覆盖。
    """
    symbols = [
        symbol
        for symbol in TRACKED_SYMBOLS
        if symbol.endswith((".SH", ".SZ", ".BJ"))
    ]
    start = (date.today() - timedelta(days=14)).isoformat()
    end = date.today().isoformat()
    rows: list[tuple] = []
    for symbol in symbols:
        bars = await findb_source.fetch_bars(
            symbol,
            freq="daily",
            start=start,
            end=end,
            order="asc",
            limit=20,
            timeout=15.0,
            retries=1,
        )
        for bar in bars:
            try:
                day = date.fromisoformat(str(bar.get("datetime"))[:10])
            except (TypeError, ValueError):
                continue
            close = _to_float(bar.get("close"))
            if close is None:
                continue
            rows.append(
                (
                    symbol,
                    "CN",
                    day,
                    _to_float(bar.get("open")),
                    _to_float(bar.get("high")),
                    _to_float(bar.get("low")),
                    close,
                    _to_int(bar.get("volume")),
                    _to_float(bar.get("amount")),
                )
            )
        # 平滑单标的请求，避免 fallback 自己制造 429。
        await asyncio.sleep(0.15)

    if not rows:
        logger.warning("findb tracked 日K fallback 无数据")
        return 0
    accepted = await quality_gate(
        "daily_prices",
        [
            {
                "symbol": row[0], "market": row[1], "date": row[2],
                "open": row[3], "high": row[4], "low": row[5],
                "close": row[6], "volume": row[7], "amount": row[8],
            }
            for row in rows
        ],
    )
    normalized = [
        (
            item["symbol"], item["market"], item["date"], item["open"],
            item["high"], item["low"], item["close"], item["volume"],
            item["amount"],
        )
        for item in accepted
    ]
    if not normalized:
        return 0
    pool = await get_pool()
    async with pool.acquire() as connection:
        for offset in range(0, len(normalized), _UPSERT_BATCH):
            await _upsert_batch(connection, normalized[offset : offset + _UPSERT_BATCH])
    await merge_daily_pool(normalized, source="findb", market="CN")
    logger.warning("同花顺日K不可用，findb fallback 补齐 tracked A 股 %d 行", len(normalized))
    return len(normalized)


async def run_hithink_daily_k_dump_job(*, full: bool = False) -> int:
    """同花顺全市场 A 股日K dump 导入，返回写入条数。

    full=False → daily-k-10d（近 10 交易日增量，CN 日K 每日主源，cron 08:30 UTC）；
    full=True  → daily-k（约 10 年全量，启动缺口自动/手动初始化，幂等可重入）。
    """
    dump_type = "daily-k" if full else "daily-k-10d"
    label = "同花顺日K全量导入" if full else "同花顺日K增量导入"
    logger.info("=== %s start (%s) ===", label, dump_type)

    path = await _ensure_dump_file(dump_type, full=full)
    if not path:
        if not full:
            fallback = await _run_findb_tracked_fallback()
            logger.warning("=== %s done: findb fallback %d rows ===", label, fallback)
            return fallback
        logger.warning("=== %s done: 0 rows（下载失败/未配置 key）===", label)
        return 0

    import pyarrow.parquet as pq

    try:
        parquet = pq.ParquetFile(path)
    except Exception as e:  # noqa: BLE001 — 打不开即降级
        if not full:
            fallback = await _run_findb_tracked_fallback()
            logger.warning(
                "=== %s done: Parquet 打开失败，findb fallback %d rows（%s）===",
                label,
                fallback,
                e,
            )
            return fallback
        logger.warning("=== %s done: 0 rows（Parquet 打开失败: %s）===", label, e)
        return 0

    pool = await get_pool()
    written = 0
    pool_rows: list[tuple] = []
    async with pool.acquire() as conn:
        batch_rows: list[tuple] = []
        for batch in parquet.iter_batches(batch_size=_PARSE_BATCH):
            cols = batch.to_pydict()
            n = batch.num_rows
            for i in range(n):
                d = _ms_to_date(cols["date_ms"][i])
                close = _to_float(cols["close_price"][i])
                if d is None or close is None:
                    continue
                batch_rows.append(
                    (
                        cols["thscode"][i],  # thscode 即规范格式（600519.SH）
                        "CN",
                        d,
                        _to_float(cols["open_price"][i]),
                        _to_float(cols["high_price"][i]),
                        _to_float(cols["low_price"][i]),
                        close,
                        _to_int(cols["volume"][i]),
                        _to_float(cols["turnover"][i]),
                    )
                )
            if batch_rows:
                # 过质量闸再写（与其他日K 源一致；逐批，内存恒定）
                dict_rows = [
                    {
                        "symbol": r[0], "market": r[1], "date": r[2],
                        "open": r[3], "high": r[4], "low": r[5],
                        "close": r[6], "volume": r[7], "amount": r[8],
                    }
                    for r in batch_rows
                ]
                accepted = await quality_gate("daily_prices", dict_rows)
                rows = [
                    (d["symbol"], d["market"], d["date"], d["open"], d["high"],
                     d["low"], d["close"], d["volume"], d["amount"])
                    for d in accepted
                ]
                for j in range(0, len(rows), _UPSERT_BATCH):
                    await _upsert_batch(conn, rows[j : j + _UPSERT_BATCH])
                # data pool 按年份分片；每日 10d 增量通常只覆盖当年，跨年时
                # merge_daily_pool 会按真实 date 拆入对应年度分片。全量任务
                # 当前由供应商初始包负责，不重复把十年数据常驻内存。
                if not full:
                    pool_rows.extend(rows)
                written += len(rows)
                batch_rows = []
            if written and written % 500_000 < _PARSE_BATCH:
                logger.info("%s 进度：已写 %s 行", label, written)

    if pool_rows:
        try:
            pool_written = await merge_daily_pool(
                pool_rows, source="hithink", market="CN"
            )
            logger.info("%s 自有 data pool 更新：%d 行", label, pool_written)
        except Exception as e:  # noqa: BLE001 — PG 已成功，冷层失败记错不回滚
            logger.error("%s 写自有 data pool 失败: %s", label, e)

    if not full and written == 0:
        written = await _run_findb_tracked_fallback()

    # 导入成功后删下载缓存，避免占盘
    if written > 0 and os.path.exists(path):
        os.remove(path)

    logger.info("=== %s done: %s rows ===", label, written)
    return written
