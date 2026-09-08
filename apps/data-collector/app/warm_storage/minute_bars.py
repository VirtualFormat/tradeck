"""分钟K 写入温层 ClickHouse 的封装（tradeck.minute_bars）。

表 schema（建表 SQL 在 compose/init 任务，不在本模块）：
    symbol LowCardinality(String), market LowCardinality(FixedString(2)),
    ts DateTime,  -- K 线起始时间，一律 UTC（纪律）
    open/high/low/close Float64, volume UInt64, amount Float64
ENGINE = MergeTree ORDER BY (symbol, ts)

幂等策略（关键设计）：分钟K 每日增量会重跑/补拉，写入必须幂等。
ClickHouse 的 MergeTree 没有 UPSERT/唯一约束，幂等只能由写入方保证：
采用「先删后插」按日分区幂等 ——
  1. delete_market_day：ALTER TABLE minute_bars DELETE WHERE market=... AND
     toDate(ts)=...（mutation 异步下发即可，对日级分区是轻操作，不等它
     执行完；同日重复 DELETE 无副作用，天然幂等）
  2. insert_market_day：JSONEachRow 批量块插（> INSERT_CHUNK_SIZE 分片）
封装为 replace_market_day(market, day, rows) 一个原子语义入口（删+插）。
任何一步失败即返回 (0, 错误摘要) 降级，绝不抛到调用方（铁律三延伸：
CH 故障不得影响 collector 的 PG/冷层写入）。

行清洗：volume 转 int、NaN→None 已由调用方 quality_gate 做过；本层做
最后防御——float('nan')/非法行拒收并计数，宁可少写也不写脏行。
"""
from __future__ import annotations

import logging
import math
from datetime import date, datetime, timezone
from typing import Any

from app.warm_storage.clickhouse_client import ClickHouseClient

logger = logging.getLogger(__name__)

TABLE = "minute_bars"

# 单次块插行数上限（分片阈值）
INSERT_CHUNK_SIZE = 500_000

# 写入列序（与表 schema 一致，供序列化与文档对照）
COLUMNS = (
    "symbol",
    "market",
    "ts",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
)


def _format_ts(ts: Any) -> str:
    """ts 统一为 UTC 的 'YYYY-MM-DD HH:MM:SS'（CH DateTime 直收）。

    接受 datetime（naive 视为 UTC / aware 转 UTC）、date、字符串
    （原样透传，调用方保证已是 UTC 格式）。
    """
    if isinstance(ts, datetime):
        if ts.tzinfo is not None:
            ts = ts.astimezone(timezone.utc).replace(tzinfo=None)
        return ts.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(ts, date):
        return ts.strftime("%Y-%m-%d %H:%M:%S")
    return str(ts)


def _is_bad_number(value: Any) -> bool:
    """拒收 NaN / ±inf。"""
    return isinstance(value, float) and (math.isnan(value) or math.isinf(value))


def serialize_rows(
    rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    """把业务行序列化为 JSONEachRow 可直写的 dict 列表。

    防御性清洗：ts 转 UTC 字符串、volume 转 int、价格/成交额转 float；
    任何字段为 NaN/inf、volume 无法转 int 的行拒收。返回 (有效行, 拒收数)。

    amount（成交额）可空：HK/US 的 findb 分钟K 不返回成交额（None），
    这类行不应被拒收——OHLCV 才是必需字段。amount 为 None 时填 0.0
    （CH 的 amount 列是 Float64 非 Nullable；成交额未知按 0 处理）。
    """
    valid: list[dict[str, Any]] = []
    rejected = 0
    for row in rows:
        try:
            # amount 可空：None → 0.0（HK/US 分钟K 无成交额字段）
            raw_amount = row.get("amount")
            amount = 0.0 if raw_amount is None else float(raw_amount)
            record = {
                "symbol": str(row["symbol"]),
                "market": str(row["market"]),
                "ts": _format_ts(row["ts"]),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": int(row["volume"]),
                "amount": amount,
            }
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            rejected += 1
            logger.warning("分钟K 行拒收（字段非法）: %s; row=%r", exc, row)
            continue
        if any(
            _is_bad_number(record[k])
            for k in ("open", "high", "low", "close", "amount")
        ):
            rejected += 1
            logger.warning("分钟K 行拒收（NaN/inf）: row=%r", row)
            continue
        valid.append(record)
    return valid, rejected


async def delete_market_day(
    client: ClickHouseClient, market: str, day: date
) -> bool:
    """下发按日分区删除的 mutation（异步，不等执行完）。

    SQL 占位符走 CH HTTP 的 {name:Type} 语法 + param_<name> 查询参数绑定，
    不手拼值（防注入）。同日重复执行无副作用（幂等）。
    """
    sql = (
        f"ALTER TABLE {TABLE} DELETE "
        "WHERE market = {m:String} AND toDate(ts) = {d:Date}"
    )
    return await client.execute(sql, params={"m": market, "d": day.isoformat()})


async def insert_market_day(
    client: ClickHouseClient, rows: list[dict[str, Any]]
) -> tuple[int, str]:
    """批量块插（已序列化行），> INSERT_CHUNK_SIZE 自动分片。

    返回 (写入行数, 错误摘要)；任一分片失败即停止并返回已写行数+摘要。
    """
    written = 0
    for start in range(0, len(rows), INSERT_CHUNK_SIZE):
        chunk = rows[start : start + INSERT_CHUNK_SIZE]
        ok = await client.insert_json_each_row(TABLE, chunk)
        if not ok:
            digest = f"块插失败（分片起始行 {start}，块大小 {len(chunk)}）"
            logger.error("ClickHouse %s %s", TABLE, digest)
            return written, digest
        written += len(chunk)
    return written, ""


async def replace_market_day(
    client: ClickHouseClient,
    market: str,
    day: date,
    rows: list[dict[str, Any]],
) -> tuple[int, str]:
    """幂等写入某市场某日的分钟K：先删后插。

    删除范围是 ``market + toDate(ts)``，因此本函数强制所有行都属于该 market：
    market 与参数不一致的行直接拒收（否则删除管不到它，重跑会产生重复行——
    实测坑：混入异市场行会被重复插入）。保证删除范围与插入内容严格对齐。

    返回 (写入行数, 错误摘要)。成功时错误摘要为空串；任何一步失败
    返回 (0, 非空摘要)，调用方据此记日志降级，本函数绝不抛异常。
    """
    mismatched = [r for r in rows if str(r.get("market")) != market]
    if mismatched:
        logger.warning(
            "ClickHouse 分钟K %s %s 拒收 %d 行异市场数据（与删除范围不一致）",
            market,
            day.isoformat(),
            len(mismatched),
        )
        rows = [r for r in rows if str(r.get("market")) == market]
    valid, rejected = serialize_rows(rows)
    if rejected:
        logger.warning(
            "ClickHouse 分钟K %s %s 拒收 %d 行（NaN/非法）",
            market,
            day.isoformat(),
            rejected,
        )

    if not await delete_market_day(client, market, day):
        digest = f"日分区删除失败 market={market} day={day.isoformat()}"
        logger.error("ClickHouse %s", digest)
        return 0, digest

    written, digest = await insert_market_day(client, valid)
    if digest:
        return 0, f"插入失败 market={market} day={day.isoformat()}: {digest}"
    return written, ""
