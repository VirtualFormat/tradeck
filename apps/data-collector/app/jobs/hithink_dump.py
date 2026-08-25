"""同花顺 Market Dumps 导入 job：全市场 A 股日K → PG（CN 日K 主源）。

链路：hithink_source.download_dump（签名 URL → Parquet 字节流）→ pyarrow
      解析 → 分批 UPSERT daily_prices。

dump 类型（契约见 Financial-API/docs/api/endpoints-market-dumps.md）：
- daily-k-10d：全市场近 10 交易日（~5.5 万行/1MB，一次请求）——每日增量主源
  （cron 挂在 scheduler `_daily_kline_cn_hk`，A 股盘后 08:30 UTC）
- daily-k：全市场约 10 年（~945 万行/170MB，下载 1-3 分钟）——首次全量初始化
  （启动缺口自动检测 / 手动触发）
- adjustment-factors：全市场复权事件（分红/送股/配股，~5.7 万行）——事件流
  而非 findb 的日频 qfq/hfq 因子，本 job 不落 adjust_factors；日频因子仍由
  findb adjust_factors job 维护，两者不冲突。

复权口径：dump 日K 为原始未复权价（adjusted=none），与 daily_prices 现有
「存原始价 + 复权因子」体系一致，UPSERT 与 TickFlow 日K 互为同源覆盖
（同 (symbol,date) 后写赢，两边都是官方原始价，数值应一致）。

纪律：单一写者（仅 collector 写）、UPSERT 幂等（(symbol,date) 冲突覆盖）、
优雅降级（未配置 key / 下载失败 / 解析失败记日志返回 0，不抛错）。
"""
from __future__ import annotations

import io
import logging
from datetime import date, datetime, timezone, timedelta
from typing import Any

from app.datasource import hithink_source
from app.db import get_pool
from app.quality import quality_gate

logger = logging.getLogger(__name__)

# UPSERT 单批行数上限（全量 daily-k 可达近千万行，分批写）
_UPSERT_BATCH = 50_000

# date_ms 为 Asia/Shanghai 零点毫秒戳 → date
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


async def _upsert_daily_prices(records: list[tuple]) -> int:
    """分批 UPSERT daily_prices，返回写入条数。"""
    if not records:
        return 0
    pool = await get_pool()
    async with pool.acquire() as conn:
        for i in range(0, len(records), _UPSERT_BATCH):
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
                records[i : i + _UPSERT_BATCH],
            )
    return len(records)


async def run_hithink_daily_k_dump_job(*, full: bool = False) -> int:
    """同花顺全市场 A 股日K dump 导入，返回写入条数。

    full=False → daily-k-10d（近 10 交易日增量，CN 日K 每日主源，cron 08:30 UTC）；
    full=True  → daily-k（约 10 年全量，启动缺口自动/手动初始化，幂等可重入）。
    """
    dump_type = "daily-k" if full else "daily-k-10d"
    label = "同花顺日K全量导入" if full else "同花顺日K增量导入"
    logger.info("=== %s start (%s) ===", label, dump_type)

    data = await hithink_source.download_dump(
        dump_type, timeout=600.0 if full else 120.0
    )
    if not data:
        logger.warning("=== %s done: 0 rows（下载失败/未配置 key）===", label)
        return 0

    import pyarrow.parquet as pq

    try:
        table = pq.read_table(io.BytesIO(data))
    except Exception as e:  # noqa: BLE001 — Parquet 解析失败整体降级
        logger.warning("=== %s done: 0 rows（Parquet 解析失败: %s）===", label, e)
        return 0

    dict_rows: list[dict] = []
    for r in table.to_pylist():
        d = _ms_to_date(r.get("date_ms"))
        close = _to_float(r.get("close_price"))
        if d is None or close is None:
            continue
        dict_rows.append(
            {
                "symbol": r["thscode"],  # thscode 即规范格式（600519.SH）
                "market": "CN",
                "date": d,
                "open": _to_float(r.get("open_price")),
                "high": _to_float(r.get("high_price")),
                "low": _to_float(r.get("low_price")),
                "close": close,
                "volume": _to_int(r.get("volume")),
                "amount": _to_float(r.get("turnover")),
            }
        )
    if not dict_rows:
        logger.warning("=== %s done: 0 rows（解析后为空）===", label)
        return 0

    # 写库前过质量闸（与其他日K 源一致）
    accepted = await quality_gate("daily_prices", dict_rows)
    rows = [
        (d["symbol"], d["market"], d["date"], d["open"], d["high"],
         d["low"], d["close"], d["volume"], d["amount"])
        for d in accepted
    ]
    written = await _upsert_daily_prices(rows)
    logger.info(
        "=== %s done: %s rows（parquet %s 行，质量闸后 %s 行）===",
        label, written, len(dict_rows), len(rows),
    )
    return written
