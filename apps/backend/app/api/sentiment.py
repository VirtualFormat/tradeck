"""GET /api/sentiment — 情绪雷达：6 维市场情绪评分（0-100）

维度（参照 tickflow，按 tradeck 数据适配）：
- 指数 index：8 只大盘指数最新涨跌幅均值
- 赚钱 profit：上涨家数占比 + 平均涨幅
- 量能 money：最新成交量 / 20 日均量
- 投机 speculation：强势股（涨幅≥2%）占比
- 抗跌 resilience：弱势股（跌幅≤-2%）占比反向
- 主线 mainline：涨幅前 5 名平均涨幅（热点强度）
"""
from __future__ import annotations

from fastapi import APIRouter
from app.db import get_pool

router = APIRouter()


def _clamp(v: float) -> int:
    return max(0, min(100, round(v)))


@router.get("/api/sentiment")
async def get_sentiment():
    pool = await get_pool()
    async with pool.acquire() as conn:
        # 报价统计（涨跌家数 / 强弱占比 / 平均涨幅）
        # 强弱阈值 ±2%（日波动，±5% 对全球市场太宽，会极化）
        quote_stats = await conn.fetchrow(
            """
            SELECT count(*) AS n,
                   avg(change_percent) AS avg_pct,
                   count(*) FILTER (WHERE change_percent > 0)::float / count(*) AS up_ratio,
                   count(*) FILTER (WHERE change_percent >= 0.02)::float / count(*) AS strong_ratio,
                   count(*) FILTER (WHERE change_percent <= -0.02)::float / count(*) AS weak_ratio
            FROM quote_snapshots
            WHERE change_percent IS NOT NULL
            """
        )
        # 涨幅前 5 平均（主线强度）
        top5_avg = await conn.fetchval(
            """
            SELECT avg(change_percent) FROM (
                SELECT change_percent FROM quote_snapshots
                WHERE change_percent IS NOT NULL
                ORDER BY change_percent DESC LIMIT 5
            ) t
            """
        )
        # 指数动能：每只指数最新两根 K 线的涨跌幅，取均值
        idx_avg = await conn.fetchval(
            """
            WITH ranked AS (
                SELECT symbol, close,
                       lag(close) OVER (PARTITION BY symbol ORDER BY date DESC) AS prev_close,
                       row_number() OVER (PARTITION BY symbol ORDER BY date DESC) AS rn
                FROM index_prices
                WHERE close IS NOT NULL AND close > 0
            )
            SELECT avg((close - prev_close) / prev_close)
            FROM ranked
            WHERE rn = 1 AND prev_close IS NOT NULL AND prev_close > 0
            """
        )
        # 量能比：最新成交量 / 前 20 日均量
        vol_ratio = await conn.fetchval(
            """
            WITH ranked AS (
                SELECT symbol, volume,
                       avg(volume) OVER (
                           PARTITION BY symbol ORDER BY date DESC
                           ROWS BETWEEN 1 PRECEDING AND 20 FOLLOWING
                       ) AS avg20,
                       row_number() OVER (PARTITION BY symbol ORDER BY date DESC) AS rn
                FROM daily_prices
                WHERE volume IS NOT NULL AND volume > 0
            )
            SELECT avg(volume / avg20) FROM ranked WHERE rn = 1 AND avg20 > 0
            """
        )

    avg_pct = float(quote_stats["avg_pct"] or 0)
    up_ratio = float(quote_stats["up_ratio"] or 0)
    strong_ratio = float(quote_stats["strong_ratio"] or 0)
    weak_ratio = float(quote_stats["weak_ratio"] or 0)

    dims = [
        {"key": "index", "label": "指数", "value": _clamp(50 + float(idx_avg or 0) * 1000)},
        {"key": "profit", "label": "赚钱", "value": _clamp(up_ratio * 70 + (50 + avg_pct * 1000) * 0.3)},
        {"key": "money", "label": "量能", "value": _clamp(float(vol_ratio or 1) / 2 * 100)},
        {"key": "speculation", "label": "投机", "value": _clamp(strong_ratio * 200)},
        {"key": "resilience", "label": "抗跌", "value": _clamp(100 - weak_ratio * 200)},
        {"key": "mainline", "label": "主线", "value": _clamp(float(top5_avg or 0) * 500)},
    ]
    score = round(sum(d["value"] for d in dims) / len(dims))

    return {"score": score, "dims": dims}
