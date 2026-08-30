"""A 股公司行为与日频复权因子任务（同花顺事件 + 本地计算）。

首次初始化（仅手动）：
  adjustment-factors 全市场 Parquet（约 5.7 万事件）→ corporate_action_events
  → 基于 daily_prices 原始未复权价，集合式重建全部 A 股 qfq/hfq 日频因子。

每日增量（09:30 UTC）：
  对活跃 A 股调用单标的公司行为 REST，仅扫描最近 14 天至未来 31 天；
  新增/变更事件的标的才全历史重算，其余标的只补新增交易日的因子。
  每日不下载全市场 adjustment-factors dump，也不重算全市场一千万行。

因子公式直接移植自 Financial-API marketdb/calculations/adjustment.py：
  ratio = prev_close * (1 + bonus + rights) /
          (prev_close - dividend + rights * rights_price)
  hfq = 从最早日累计 ratio；qfq = hfq / 最新日 hfq。
"""
from __future__ import annotations

import io
import logging
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo

import pyarrow.parquet as pq

from app.datasource import hithink_source
from app.db import get_pool

logger = logging.getLogger(__name__)

_SHANGHAI = ZoneInfo("Asia/Shanghai")
_INCREMENTAL_OVERLAP_DAYS = 14
_INCREMENTAL_FUTURE_DAYS = 31

_EVENT_UPSERT_SQL = """
    INSERT INTO corporate_action_events
        (symbol, ex_date, dividend_per_share, per_share_bonus,
         allotment_ratio, allotment_price, currency, source, fetched_at)
    VALUES ($1, $2, $3, $4, $5, $6, $7, 'hithink', NOW())
    ON CONFLICT (symbol, ex_date) DO UPDATE SET
        dividend_per_share = EXCLUDED.dividend_per_share,
        per_share_bonus = EXCLUDED.per_share_bonus,
        allotment_ratio = EXCLUDED.allotment_ratio,
        allotment_price = EXCLUDED.allotment_price,
        currency = EXCLUDED.currency,
        source = EXCLUDED.source,
        fetched_at = NOW()
"""


def _ms_to_date(value: Any) -> date | None:
    try:
        return datetime.fromtimestamp(int(value) / 1000, tz=_SHANGHAI).date()
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _decimal(value: Any) -> Decimal:
    if value is None:
        return Decimal("0")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")
    return Decimal("0") if not result.is_finite() else result


def _event_record(symbol: str, row: dict[str, Any]) -> tuple | None:
    ex_date = _ms_to_date(row.get("ex_date_ms"))
    if ex_date is None:
        return None
    return (
        symbol,
        ex_date,
        _decimal(row.get("dividend_per_share")),
        _decimal(row.get("per_share_bonus")),
        _decimal(row.get("allotment_ratio")),
        _decimal(row.get("allotment_price")),
        str(row.get("currency") or "CNY"),
    )


async def _store_events(records: list[tuple], *, replace_full: bool = False) -> int:
    if not records and not replace_full:
        return 0
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            if replace_full:
                await conn.execute(
                    "DELETE FROM corporate_action_events WHERE source = 'hithink'"
                )
            if records:
                await conn.executemany(_EVENT_UPSERT_SQL, records)
    return len(records)


async def rebuild_adjustment_factors(symbols: list[str] | None = None) -> int:
    """按 Financial-API 标准公式重建全部 A 股或指定标的日频因子。"""
    if symbols is not None and not symbols:
        return 0

    if symbols is None:
        price_scope = "p.market = 'CN'"
        event_scope = (
            "e.symbol IN (SELECT DISTINCT symbol FROM daily_prices WHERE market = 'CN')"
        )
        delete_scope = (
            "symbol IN (SELECT DISTINCT symbol FROM daily_prices WHERE market = 'CN')"
        )
        args: list[Any] = []
    else:
        price_scope = "p.symbol = ANY($1::text[])"
        event_scope = "e.symbol = ANY($1::text[])"
        delete_scope = "symbol = ANY($1::text[])"
        args = [symbols]

    sql = f"""
        WITH events AS (
            SELECT
                e.symbol,
                e.ex_date,
                COALESCE(e.dividend_per_share, 0)::double precision AS d,
                COALESCE(e.per_share_bonus, 0)::double precision AS s,
                COALESCE(e.allotment_ratio, 0)::double precision AS r,
                COALESCE(e.allotment_price, 0)::double precision AS rights_price
            FROM corporate_action_events e
            WHERE {event_scope}
        ),
        effective_event AS (
            SELECT e.*,
                   (
                       SELECT MIN(p2.date)
                       FROM daily_prices p2
                       WHERE p2.symbol = e.symbol AND p2.date >= e.ex_date
                   ) AS eff_date
            FROM events e
        ),
        kline_with_prev AS (
            SELECT p.symbol, p.date, p.close::double precision AS close,
                   LAG(p.close::double precision) OVER (
                       PARTITION BY p.symbol ORDER BY p.date
                   ) AS prev_close
            FROM daily_prices p
            WHERE {price_scope}
        ),
        event_ratios AS (
            SELECT e.symbol, e.eff_date AS date,
                   (kp.prev_close * (1.0 + e.s + e.r)) /
                   NULLIF(kp.prev_close - e.d + e.r * e.rights_price, 0) AS ratio
            FROM effective_event e
            JOIN kline_with_prev kp
              ON kp.symbol = e.symbol AND kp.date = e.eff_date
            WHERE e.eff_date IS NOT NULL AND kp.prev_close IS NOT NULL
        ),
        ratio_per_day AS (
            SELECT symbol, date, EXP(SUM(LN(ratio))) AS day_ratio
            FROM event_ratios
            WHERE ratio IS NOT NULL AND ratio > 0
            GROUP BY symbol, date
        ),
        kline_ratio AS (
            SELECT k.symbol, k.date, COALESCE(r.day_ratio, 1.0) AS day_ratio
            FROM kline_with_prev k
            LEFT JOIN ratio_per_day r USING (symbol, date)
        ),
        backward AS (
            SELECT symbol, date,
                   EXP(SUM(LN(day_ratio)) OVER (
                       PARTITION BY symbol ORDER BY date
                       ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                   )) AS backward_factor
            FROM kline_ratio
        ),
        normalized AS (
            SELECT symbol, date, backward_factor,
                   LAST_VALUE(backward_factor) OVER (
                       PARTITION BY symbol ORDER BY date
                       ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
                   ) AS last_backward
            FROM backward
        )
        INSERT INTO adjust_factors (symbol, date, qfq, hfq, fetched_at)
        SELECT symbol, date,
               (backward_factor / NULLIF(last_backward, 0))::numeric(20,8),
               backward_factor::numeric(20,8),
               NOW()
        FROM normalized
    """

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("SET LOCAL work_mem = '128MB'")
            await conn.execute(
                f"DELETE FROM adjust_factors WHERE {delete_scope}", *args
            )
            status = await conn.execute(sql, *args)
    return int(status.rsplit(" ", 1)[-1])


async def append_missing_adjustment_factors(
    *, excluded_symbols: list[str] | None = None,
) -> int:
    """给无新事件的 A 股新增交易日追加因子（qfq=1，hfq延续最近值）。"""
    excluded = excluded_symbols or []
    pool = await get_pool()
    async with pool.acquire() as conn:
        status = await conn.execute(
            """
            INSERT INTO adjust_factors (symbol, date, qfq, hfq, fetched_at)
            SELECT p.symbol, p.date, 1.0,
                   COALESCE(last_factor.hfq, 1.0), NOW()
            FROM daily_prices p
            LEFT JOIN adjust_factors current_factor
              ON current_factor.symbol = p.symbol AND current_factor.date = p.date
            LEFT JOIN LATERAL (
                SELECT f.hfq
                FROM adjust_factors f
                WHERE f.symbol = p.symbol AND f.date < p.date
                ORDER BY f.date DESC
                LIMIT 1
            ) last_factor ON TRUE
            WHERE p.market = 'CN'
              AND p.date >= CURRENT_DATE - 45
              AND current_factor.symbol IS NULL
              AND NOT (p.symbol = ANY($1::text[]))
            ON CONFLICT (symbol, date) DO NOTHING
            """,
            excluded,
        )
    return int(status.rsplit(" ", 1)[-1])


async def run_adjust_factors_full_job() -> int:
    """首次全量：导入同花顺全市场事件 dump，并重建全部 A 股日频因子。"""
    logger.info("=== adjustment factors full job start ===")
    payload = await hithink_source.download_dump("adjustment-factors", timeout=180.0)
    if not payload:
        logger.warning(
            "=== adjustment factors full job done: 0 rows（dump 下载失败）==="
        )
        return 0

    try:
        table = pq.read_table(io.BytesIO(payload))
    except Exception as exc:  # noqa: BLE001
        logger.warning("复权事件 Parquet 解析失败: %s", exc)
        return 0

    records = []
    for row in table.to_pylist():
        symbol = str(row.get("thscode") or "").strip().upper()
        record = _event_record(symbol, row) if symbol else None
        if record:
            records.append(record)
    await _store_events(records, replace_full=True)
    factors = await rebuild_adjustment_factors()
    logger.info(
        "=== adjustment factors full job done: %d events, %d factor rows ===",
        len(records),
        factors,
    )
    return factors


async def run_adjust_factors_job() -> dict[str, int]:
    """每日增量：短窗口扫描事件，局部重算受影响标的，追加普通交易日因子。"""
    logger.info("=== adjustment factors incremental job start ===")
    pool = await get_pool()
    async with pool.acquire() as conn:
        initialized = await conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM corporate_action_events)"
        )
        if not initialized:
            logger.warning(
                "=== adjustment factors incremental job done: 0 "
                "（尚未执行 adjust_factors_full 首次全量初始化）==="
            )
            return {"events": 0, "factors": 0, "failed_symbols": -1}
        symbols = list(
            await conn.fetchval(
                """
                SELECT array_agg(symbol ORDER BY symbol)
                FROM (
                    SELECT symbol
                    FROM daily_prices
                    WHERE market = 'CN' AND date >= CURRENT_DATE - 30
                    GROUP BY symbol
                ) active
                """
            )
            or []
        )
    if not symbols:
        logger.warning(
            "=== adjustment factors incremental job done: 0（无活跃 A 股）==="
        )
        return {"events": 0, "factors": 0, "failed_symbols": 0}

    today = date.today()
    date_from = today - timedelta(days=_INCREMENTAL_OVERLAP_DAYS)
    date_to = today + timedelta(days=_INCREMENTAL_FUTURE_DAYS)
    events_by_symbol, failed = await hithink_source.scan_adjustment_events(
        symbols,
        date_from=date_from,
        date_to=date_to,
    )

    records = []
    for symbol, items in events_by_symbol.items():
        for item in items:
            record = _event_record(symbol, item)
            if record:
                records.append(record)
    await _store_events(records)

    # overlap 内返回过事件、或近期事件刚到生效日的标的都局部全历史重算。
    affected = set(events_by_symbol)
    async with pool.acquire() as conn:
        recent_event_symbols = await conn.fetch(
            """
            SELECT DISTINCT symbol
            FROM corporate_action_events
            WHERE ex_date BETWEEN $1 AND $2
            """,
            date_from,
            date_to,
        )
    affected.update(row["symbol"] for row in recent_event_symbols)

    rebuilt = await rebuild_adjustment_factors(sorted(affected)) if affected else 0
    appended = await append_missing_adjustment_factors(
        excluded_symbols=sorted(affected)
    )
    logger.info(
        "=== adjustment factors incremental job done: %d events, %d affected, "
        "%d rebuilt, %d appended, %d failed symbols ===",
        len(records),
        len(affected),
        rebuilt,
        appended,
        failed,
    )
    result = {
        "events": len(records),
        "factors": rebuilt + appended,
    }
    # 任务分类器把值为 0 的数据分项视为 partial；仅真实失败时附带负值。
    if failed:
        result["failed_symbols"] = -failed
    return result
