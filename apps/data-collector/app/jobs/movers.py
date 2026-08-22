"""异动榜。

- 美股：OpenBB/yfinance discovery，写入 movers_cache。
- A 股：从 TickFlow 全市场 daily_prices 最新两根日 K 本地计算，
  涨跌榜按涨跌幅、活跃榜按成交额排序。

榜单是日快照模型；同日重跑覆盖同一市场/类型，历史日期保留给前端回看。
"""

from __future__ import annotations

import logging
from typing import Any

from app.db import get_pool
from app.openbb_client import fetch_openbb

logger = logging.getLogger(__name__)

_MOVER_TYPES = ("gainers", "losers", "active")
_US_SORT = {
    "gainers": ("percent_change", True),
    "losers": ("percent_change", False),
    "active": ("volume", True),
}
_LIMIT = 20


def _number(value: Any) -> float | None:
    try:
        result = float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
    return None if result is not None and result != result else result


def _sort_us_results(mover_type: str, results: list[dict]) -> list[dict]:
    """显式排序，避免依赖 yfinance discovery 的上游返回顺序。"""
    field, reverse = _US_SORT[mover_type]
    valid = [r for r in results if _number(r.get(field)) is not None]
    return sorted(
        valid,
        key=lambda item: _number(item.get(field)) or 0,
        reverse=reverse,
    )


async def _replace_snapshot(
    market: str,
    mover_type: str,
    snapshot_date,
    rows: list[tuple],
) -> int:
    if not rows:
        return 0
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                """
                DELETE FROM movers_cache
                WHERE market = $1 AND type = $2 AND snapshot_date = $3
                """,
                market,
                mover_type,
                snapshot_date,
            )
            await conn.executemany(
                """
                INSERT INTO movers_cache
                    (type, market, rank, symbol, name, price, percent_change,
                     volume, amount, snapshot_date, updated_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, NOW())
                """,
                rows,
            )
    return len(rows)


async def fetch_and_store_us_movers() -> int:
    """拉美股涨跌榜 + 活跃榜，显式排序后写库。"""
    total = 0
    for mover_type in _MOVER_TYPES:
        data = await fetch_openbb(
            f"/equity/discovery/{mover_type}",
            {"provider": "yfinance"},
        )
        results = data.get("results", [])
        sorted_results = _sort_us_results(mover_type, results)
        if not sorted_results:
            logger.warning(f"US movers [{mover_type}] empty, keep old snapshot")
            continue

        rows = []
        for rank, item in enumerate(sorted_results[:_LIMIT], 1):
            price = _number(item.get("price"))
            volume = item.get("volume")
            amount = (
                price * volume if price is not None and volume is not None else None
            )
            rows.append(
                (
                    mover_type,
                    "US",
                    rank,
                    item.get("symbol"),
                    item.get("name"),
                    price,
                    _number(item.get("percent_change")),
                    volume,
                    amount,
                    None,
                )
            )
        pool = await get_pool()
        async with pool.acquire() as conn:
            existing_date = await conn.fetchval(
                """
                SELECT max(snapshot_date)
                FROM movers_cache
                WHERE market = 'US' AND type = $1
                """,
                mover_type,
            )
            new_york_date = await conn.fetchval(
                "SELECT (NOW() AT TIME ZONE 'America/New_York')::date"
            )
        snapshot_date = (
            new_york_date
            if existing_date is None or existing_date < new_york_date
            else existing_date
        )
        rows = [(*row[:-1], snapshot_date) for row in rows]
        count = await _replace_snapshot("US", mover_type, snapshot_date, rows)
        total += count
        logger.info(f"US movers [{mover_type}]: source={len(results)} stored={count}")
    return total


_CN_CANDIDATES_SQL = """
WITH latest_market_date AS (
    SELECT date AS snapshot_date
    FROM daily_prices
    WHERE market = 'CN'
      AND close IS NOT NULL
      AND close > 0
    GROUP BY date
    ORDER BY date DESC
    LIMIT 1
),
latest AS (
    SELECT d.symbol, d.date, d.close, d.volume, d.amount
    FROM daily_prices d, latest_market_date m
    WHERE d.market = 'CN'
      AND d.date = m.snapshot_date
      AND d.close IS NOT NULL
      AND d.close > 0
),
latest_with_previous AS (
    SELECT l.symbol, l.date, l.close, l.volume, l.amount,
           p.date AS previous_date, p.close AS previous_close
    FROM latest l
    JOIN LATERAL (
        SELECT date, close
        FROM daily_prices
        WHERE market = 'CN'
          AND symbol = l.symbol
          AND date < l.date
          AND close IS NOT NULL
          AND close > 0
        ORDER BY date DESC
        LIMIT 1
    ) p ON TRUE
    WHERE l.date - p.date <= 7
),
coverage AS (
    SELECT l.date AS snapshot_date,
           count(*) AS latest_count,
           count(*) FILTER (
               WHERE l.amount IS NOT NULL AND l.amount > 0
           ) AS amount_count,
           (
               SELECT count(DISTINCT symbol)
               FROM daily_prices
               WHERE market = 'CN'
           ) AS universe_count
    FROM latest l
    GROUP BY l.date
)
SELECT l.symbol,
       COALESCE(NULLIF(p.name, ''), l.symbol) AS name,
       l.date AS snapshot_date,
       l.close AS price,
       (l.close - l.previous_close) / l.previous_close AS percent_change,
       l.volume,
       l.amount,
       c.latest_count,
       c.amount_count,
       c.universe_count
FROM latest_with_previous l
JOIN coverage c ON c.snapshot_date = l.date
LEFT JOIN equity_profiles p ON p.symbol = l.symbol
"""


async def fetch_and_store_cn_movers() -> int:
    """从 A 股全市场最新两根日 K 计算涨跌榜和成交额活跃榜。"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        candidates = await conn.fetch(_CN_CANDIDATES_SQL)
    if not candidates:
        logger.warning("CN movers empty, keep old snapshot")
        return 0

    snapshot_date = candidates[0]["snapshot_date"]
    latest_count = int(candidates[0]["latest_count"] or 0)
    amount_count = int(candidates[0]["amount_count"] or 0)
    universe_count = int(candidates[0]["universe_count"] or 0)
    if universe_count and latest_count < universe_count * 0.6:
        logger.warning(
            f"CN movers {snapshot_date}: latest coverage {latest_count}/{universe_count} "
            "below 60%, keep old snapshot"
        )
        return 0

    gainers = sorted(
        candidates,
        key=lambda row: float(row["percent_change"]),
        reverse=True,
    )[:_LIMIT]
    losers = sorted(
        candidates,
        key=lambda row: float(row["percent_change"]),
    )[:_LIMIT]
    active_candidates = [row for row in candidates if row["amount"] is not None]
    active = (
        sorted(
            active_candidates,
            key=lambda row: float(row["amount"]),
            reverse=True,
        )[:_LIMIT]
        if amount_count >= _LIMIT
        else []
    )

    total = 0
    for mover_type, selected in (
        ("gainers", gainers),
        ("losers", losers),
        ("active", active),
    ):
        rows = [
            (
                mover_type,
                "CN",
                rank,
                row["symbol"],
                row["name"],
                row["price"],
                row["percent_change"],
                row["volume"],
                row["amount"],
                snapshot_date,
            )
            for rank, row in enumerate(selected, 1)
        ]
        if mover_type == "active" and not rows:
            logger.warning(
                f"CN movers {snapshot_date}: amount coverage {amount_count}/{latest_count}, "
                "active snapshot not updated"
            )
            continue
        total += await _replace_snapshot("CN", mover_type, snapshot_date, rows)

    logger.info(
        f"CN movers {snapshot_date}: candidates={len(candidates)} "
        f"coverage={latest_count}/{universe_count} amount={amount_count} stored={total}"
    )
    return total


async def fetch_and_store_movers() -> int:
    """兼容旧调用：刷新美股和 A 股榜单，返回总写入条数。"""
    us_count = await fetch_and_store_us_movers()
    cn_count = await fetch_and_store_cn_movers()
    return us_count + cn_count


async def run_movers_job() -> int:
    """高频任务：刷新美股榜单；A 股榜单由日 K 完成后刷新。"""
    logger.info("=== movers job start ===")
    count = await fetch_and_store_us_movers()
    logger.info(f"=== movers job done: US={count} rows ===")
    return count
