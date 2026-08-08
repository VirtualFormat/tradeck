"""US/HK 市场宽度（每日 job，从 daily_prices 全市场日K 计算涨跌家数，写入 market_breadth）

CN 宽度走 legu 实时快照（market_breadth.py）；美股/港股无免费实时家数接口，
故用日K 自算：先按每日标的覆盖数选择最近的有效交易日，再对当日出现的每个 symbol
取不晚于该日的两根 K（走 (symbol,date) 索引，禁止笛卡尔扫描）。两根日期相邻时才计入。

- 涨/跌/平：涨跌额 >0 / <0 / |涨跌幅| ≤ 0.01% 为平；
- 只算 up_count/down_count/flat_count；limit 系列与 activity_rate 置 null。
- snapshot_date = 该市场 K 线最新交易日；同日重跑 UPSERT 覆盖当天行。
"""
from __future__ import annotations

import logging

from app.db import get_pool

logger = logging.getLogger(__name__)

# 目标市场及有效交易日的最低日 K 覆盖。门槛显著高于 tracked/seed 数量，
# 同时为当前 TickFlow universe（US 约 1.1 万、HK 约 2,800）保留足够余量。
MARKET_COVERAGE_THRESHOLDS = {"US": 5_000, "HK": 1_000}
_MARKETS = tuple(MARKET_COVERAGE_THRESHOLDS)


def coverage_threshold(market: str) -> int | None:
    """返回 US/HK 有效宽度快照的最低覆盖数；其他市场不设此门槛。"""
    return MARKET_COVERAGE_THRESHOLDS.get(market.upper())


def has_sufficient_coverage(market: str, coverage_count: int) -> bool:
    """纯函数：判断市场宽度的实际参与计算标的数是否达到门槛。"""
    threshold = coverage_threshold(market)
    return threshold is None or coverage_count >= threshold


# 候选日只查看最近 14 个有数据的日期，再按 market/date 聚合选择最近有效日；
# daily_prices 的 (symbol, date) 唯一约束保证每组 count(*) 即 distinct symbol 数。
# 随后仅对有效日 universe 做 LATERAL 索引回看，不把历史行相互连接。
_BREADTH_SQL = """
WITH candidate_days AS MATERIALIZED (
    SELECT DISTINCT date
    FROM daily_prices
    WHERE market = $1
      AND date >= CURRENT_DATE - 30
    ORDER BY date DESC
    LIMIT 14
),
valid_day AS (
    SELECT date AS snapshot_date, count(*)::int AS universe_count
    FROM daily_prices
    WHERE market = $1
      AND date IN (SELECT date FROM candidate_days)
      AND close IS NOT NULL AND close > 0
    GROUP BY date
    HAVING count(*) >= $2
    ORDER BY date DESC
    LIMIT 1
),
universe AS (
    SELECT p.symbol, d.snapshot_date, d.universe_count
    FROM valid_day d
    JOIN daily_prices p
      ON p.market = $1
     AND p.date = d.snapshot_date
     AND p.close IS NOT NULL
     AND p.close > 0
),
latest AS (
    SELECT u.symbol, u.snapshot_date, u.universe_count,
           k.date, k.close, k.rn
    FROM universe u
    CROSS JOIN LATERAL (
        SELECT date, close, row_number() OVER (ORDER BY date DESC) AS rn
        FROM daily_prices
        WHERE symbol = u.symbol AND market = $1
          AND date <= u.snapshot_date
          AND close IS NOT NULL AND close > 0
        ORDER BY date DESC
        LIMIT 2
    ) k
),
paired AS (
    SELECT symbol, snapshot_date, universe_count,
           max(date)  FILTER (WHERE rn = 1) AS d1,
           max(close) FILTER (WHERE rn = 1) AS c1,
           max(date)  FILTER (WHERE rn = 2) AS d0,
           max(close) FILTER (WHERE rn = 2) AS c0,
           count(*) AS n
    FROM latest
    GROUP BY symbol, snapshot_date, universe_count
),
valid AS (
    SELECT snapshot_date, universe_count, (c1 - c0) / c0 AS pct
    FROM paired
    WHERE n = 2
      AND d1 = snapshot_date                  -- 最新 K 必须落在选定有效日
      AND (d1 - d0) <= 7                      -- 容周末/假期，排除长停牌
)
SELECT
    max(snapshot_date) AS snapshot_date,
    max(universe_count) AS universe_count,
    count(*) FILTER (WHERE abs(pct) <= 0.0001) AS flat_count,
    count(*) FILTER (WHERE pct > 0.0001) AS up_count,
    count(*) FILTER (WHERE pct < -0.0001) AS down_count,
    count(*)::int AS coverage_count
FROM valid
"""

_UPSERT_SQL = """
INSERT INTO market_breadth
    (date, market, up_count, down_count, flat_count,
     limit_up_count, limit_down_count,
     real_limit_up_count, real_limit_down_count,
     suspended_count, activity_rate, source, fetched_at)
VALUES ($1, $2, $3, $4, $5, NULL, NULL, NULL, NULL, NULL, NULL, 'daily_kline', NOW())
ON CONFLICT (date, market) DO UPDATE SET
    up_count = EXCLUDED.up_count,
    down_count = EXCLUDED.down_count,
    flat_count = EXCLUDED.flat_count,
    source = EXCLUDED.source,
    fetched_at = NOW()
"""


async def run_market_breadth_global_job() -> dict[str, int]:
    """定时任务：从 daily_prices 计算 US/HK 涨跌家数，UPSERT market_breadth（K线最新交易日）"""
    logger.info("=== market breadth global job start ===")
    pool = await get_pool()
    results = {market: 0 for market in _MARKETS}
    async with pool.acquire() as conn:
        for market in _MARKETS:
            threshold = MARKET_COVERAGE_THRESHOLDS[market]
            row = await conn.fetchrow(_BREADTH_SQL, market, threshold)
            snapshot_date = row["snapshot_date"] if row else None
            if snapshot_date is None:
                logger.warning(
                    f"market breadth global [{market}]: "
                    f"无覆盖至少 {threshold} 只的日K交易日，跳过"
                )
                continue
            up = int(row["up_count"] or 0)
            down = int(row["down_count"] or 0)
            flat = int(row["flat_count"] or 0)
            coverage_count = int(row["coverage_count"] or 0)
            universe_count = int(row["universe_count"] or 0)
            if not has_sufficient_coverage(market, coverage_count):
                logger.warning(
                    f"market breadth global [{market}] {snapshot_date}: "
                    f"有效比较仅 {coverage_count}/{universe_count} 只，"
                    f"低于门槛 {threshold}，跳过"
                )
                continue
            await conn.execute(
                _UPSERT_SQL, snapshot_date, market, up, down, flat
            )
            results[market] = 1
            logger.info(
                f"market breadth global [{market}] {snapshot_date}: "
                f"up={up} down={down} flat={flat} "
                f"coverage={coverage_count}/{universe_count}"
            )
    logger.info(
        f"=== market breadth global job done: {sum(results.values())} rows ==="
    )
    return results
