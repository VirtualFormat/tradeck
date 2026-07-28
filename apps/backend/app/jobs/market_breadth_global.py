"""US/HK 市场宽度（每日 job，从 daily_prices 全市场日K 计算涨跌家数，写入 market_breadth）

CN 宽度走 legu 实时快照（market_breadth.py）；美股/港股无免费实时家数接口，
故用日K 全市场自算：每 symbol 取最新两根 K（走 (symbol,date) 索引，禁止全表按 date 算），
最新一根须落在全市场最新交易日、两根日期相邻（防停牌陈旧数据）才计入。

- 涨/跌/平：涨跌额 >0 / <0 / |涨跌幅| ≤ 0.01% 为平；
- 只算 up_count/down_count/flat_count；limit 系列与 activity_rate 置 null。
- snapshot_date = 该市场 K 线最新交易日；同日重跑 UPSERT 覆盖当天行。
"""
from __future__ import annotations

import logging

from app.db import get_pool

logger = logging.getLogger(__name__)

# 目标市场（CN 由 legu job 负责，不在此列）
_MARKETS = ("US", "HK")

# 每 symbol 取最新两根 K（CROSS JOIN LATERAL 走 (symbol,date) 索引，避免全表按 date 算 300 万+ 行）；
# 仅当最新一根落在全市场最新交易日、两根日期相邻（≤7 天容周末/假期，长停牌排除）才计入。
_BREADTH_SQL = """
WITH universe AS (
    SELECT DISTINCT symbol FROM daily_prices WHERE market = $1
),
latest AS (
    SELECT u.symbol, k.date, k.close, k.rn
    FROM universe u
    CROSS JOIN LATERAL (
        SELECT date, close, row_number() OVER (ORDER BY date DESC) AS rn
        FROM daily_prices
        WHERE symbol = u.symbol AND market = $1
          AND close IS NOT NULL AND close > 0
        ORDER BY date DESC
        LIMIT 2
    ) k
),
paired AS (
    SELECT symbol,
           max(date)  FILTER (WHERE rn = 1) AS d1,
           max(close) FILTER (WHERE rn = 1) AS c1,
           max(date)  FILTER (WHERE rn = 2) AS d0,
           max(close) FILTER (WHERE rn = 2) AS c0,
           count(*) AS n
    FROM latest
    GROUP BY symbol
),
snap AS (
    SELECT max(d1) AS snapshot_date FROM paired
),
valid AS (
    SELECT (p.c1 - p.c0) / p.c0 AS pct
    FROM paired p, snap
    WHERE p.n = 2
      AND snap.snapshot_date IS NOT NULL
      AND p.d1 = snap.snapshot_date          -- 最新 K 落在全市场最新交易日（剔停牌陈旧数据）
      AND (p.d1 - p.d0) <= 7                  -- 两根相邻（容周末/假期，长停牌排除）
)
SELECT
    (SELECT snapshot_date FROM snap) AS snapshot_date,
    count(*) FILTER (WHERE abs(pct) <= 0.0001) AS flat_count,
    count(*) FILTER (WHERE pct > 0.0001) AS up_count,
    count(*) FILTER (WHERE pct < -0.0001) AS down_count
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


async def run_market_breadth_global_job() -> int:
    """定时任务：从 daily_prices 计算 US/HK 涨跌家数，UPSERT market_breadth（K线最新交易日）"""
    logger.info("=== market breadth global job start ===")
    pool = await get_pool()
    written = 0
    async with pool.acquire() as conn:
        for market in _MARKETS:
            row = await conn.fetchrow(_BREADTH_SQL, market)
            snapshot_date = row["snapshot_date"] if row else None
            if snapshot_date is None:
                logger.warning(f"market breadth global [{market}]: 无日K 数据，跳过")
                continue
            up = int(row["up_count"] or 0)
            down = int(row["down_count"] or 0)
            flat = int(row["flat_count"] or 0)
            await conn.execute(
                _UPSERT_SQL, snapshot_date, market, up, down, flat
            )
            written += 1
            logger.info(
                f"market breadth global [{market}] {snapshot_date}: "
                f"up={up} down={down} flat={flat}"
            )
    logger.info(f"=== market breadth global job done: {written} rows ===")
    return written
