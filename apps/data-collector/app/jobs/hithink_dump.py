"""同花顺 Market Dumps 导入 job：全市场 A 股日K → PG（CN 日K 主源）。

链路：签名 URL → 流式下载落盘缓存（可复用）→ pyarrow 分批解析 → 分批 UPSERT。

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

import logging
import os
import tempfile
import time
from datetime import date, datetime, timezone, timedelta
from typing import Any

import httpx

from app.datasource import hithink_source
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
        logger.warning("=== %s done: 0 rows（下载失败/未配置 key）===", label)
        return 0

    import pyarrow.parquet as pq

    try:
        parquet = pq.ParquetFile(path)
    except Exception as e:  # noqa: BLE001 — 打不开即降级
        logger.warning("=== %s done: 0 rows（Parquet 打开失败: %s）===", label, e)
        return 0

    pool = await get_pool()
    written = 0
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
                written += len(rows)
                batch_rows = []
            if written and written % 500_000 < _PARSE_BATCH:
                logger.info("%s 进度：已写 %s 行", label, written)

    # 导入成功后删全量缓存（增量小文件也顺手清），避免占盘
    if written > 0 and os.path.exists(path):
        os.remove(path)

    logger.info("=== %s done: %s rows ===", label, written)
    return written
