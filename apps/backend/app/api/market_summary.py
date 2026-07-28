"""GET /api/market-summary — 三市对比总览（CN/US/HK 市场宽度最新行）

只读 market_breadth：
- CN 来自 legu 实时快照（含涨跌停/活跃度）；
- US/HK 来自日K 全市场自算（market_breadth_global job，仅涨/跌/平，limit 系列为 null）。

支持 ?date= 查历史（每市取「不晚于该日期」的最近一行）；无 date 则各市取最新行。
返回扁平数组 [{market, date, up, down, flat, limit_up, limit_down, total, up_ratio}]，
up_ratio = up / (up + down)（平盘不计入分母，后端算好）。
"""
from __future__ import annotations

from datetime import date as date_type

from fastapi import APIRouter, Query

from app.db import get_pool

router = APIRouter()

_MARKETS = ("CN", "US", "HK")


def _row_to_dict(r) -> dict:
    up = r["up_count"] or 0
    down = r["down_count"] or 0
    flat = r["flat_count"] or 0
    denom = up + down
    up_ratio = round(up / denom, 4) if denom > 0 else None
    return {
        "market": r["market"],
        "date": r["date"].isoformat() if r["date"] else None,
        "up": up,
        "down": down,
        "flat": flat,
        "limit_up": r["limit_up_count"],
        "limit_down": r["limit_down_count"],
        "total": up + down + flat,
        "up_ratio": up_ratio,
    }


@router.get("/api/market-summary")
async def get_market_summary(date: str | None = Query(None)):
    """三市（CN/US/HK）市场宽度最新行；?date= 查历史（回退到不晚于该日期的最近一行）。"""
    snapshot_date: date_type | None = None
    if date:
        try:
            snapshot_date = date_type.fromisoformat(date)
        except ValueError:
            snapshot_date = None

    pool = await get_pool()
    result: list[dict] = []
    async with pool.acquire() as conn:
        for market in _MARKETS:
            if snapshot_date is not None:
                row = await conn.fetchrow(
                    """
                    SELECT date, market, up_count, down_count, flat_count,
                           limit_up_count, limit_down_count
                    FROM market_breadth
                    WHERE market = $1 AND date <= $2
                    ORDER BY date DESC
                    LIMIT 1
                    """,
                    market,
                    snapshot_date,
                )
            else:
                row = await conn.fetchrow(
                    """
                    SELECT date, market, up_count, down_count, flat_count,
                           limit_up_count, limit_down_count
                    FROM market_breadth
                    WHERE market = $1
                    ORDER BY date DESC
                    LIMIT 1
                    """,
                    market,
                )
            if row is not None:
                result.append(_row_to_dict(row))
    return result
