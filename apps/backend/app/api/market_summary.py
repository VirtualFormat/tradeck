"""GET /api/market-summary — 三市对比总览（CN/US/HK 市场宽度最新行）

只读 market_breadth：
- CN 来自 legu 实时快照（含涨跌停/活跃度）；
- US/HK 来自日K 宽覆盖自算（market_breadth_global job，仅涨/跌/平，limit 系列为 null）。

支持 ?date= 查历史（每市取「不晚于该日期」的最近合格行）；无 date 则各市取最新合格行。
US/HK 只读取 source=daily_kline 且达到日 K 覆盖门槛的快照，CN 不限制来源。
coverage_count 表示参与涨跌比较的标的数（up + down + flat），不是原始 universe 数。
source/fetched_at 原样返回，供前端明确展示数据来源与采集时间。
"""
from __future__ import annotations

from datetime import date as date_type

from fastapi import APIRouter, Depends, Query

from app.api._service_auth import read_access
from app.db import get_pool

# 全文件读接口统一挂 read_access（配置 SERVICE_TOKENS 后强制 X-Service-Token）
router = APIRouter(dependencies=[Depends(read_access)])

_MARKETS = ("CN", "US", "HK")

# US/HK 市场宽度自算的最低日K覆盖门槛（与 collector 的 market_breadth_global
# job 口径一致：覆盖不足的日快照视为无效，不展示）。纯常量，无进程依赖。
MARKET_COVERAGE_THRESHOLDS = {"US": 5_000, "HK": 1_000}


def _coverage_threshold(market: str) -> int | None:
    """返回 US/HK 市场宽度最低覆盖门槛；CN 不设门槛。"""
    return MARKET_COVERAGE_THRESHOLDS.get(market.upper())


def _has_sufficient_coverage(market: str, coverage_count: int) -> bool:
    """判断 API 快照是否达到该市场最低覆盖门槛。"""
    threshold = _coverage_threshold(market)
    return threshold is None or coverage_count >= threshold


def _row_to_dict(r) -> dict:
    """转换宽度快照；coverage_count 是实际参与涨跌比较的标的数。"""
    up = r["up_count"] or 0
    down = r["down_count"] or 0
    flat = r["flat_count"] or 0
    denom = up + down
    up_ratio = round(up / denom, 4) if denom > 0 else None
    coverage_count = up + down + flat
    threshold = _coverage_threshold(r["market"])
    return {
        "market": r["market"],
        "date": r["date"].isoformat() if r["date"] else None,
        "source": r["source"],
        "fetched_at": r["fetched_at"].isoformat() if r["fetched_at"] else None,
        "up": up,
        "down": down,
        "flat": flat,
        "limit_up": r["limit_up_count"],
        "limit_down": r["limit_down_count"],
        "total": coverage_count,
        "coverage_count": coverage_count,
        "coverage_min": threshold,
        "coverage_sufficient": _has_sufficient_coverage(
            r["market"], coverage_count
        ),
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
            threshold = _coverage_threshold(market)
            coverage_filter = (
                ""
                if threshold is None
                else """
                AND source = 'daily_kline'
                AND (COALESCE(up_count, 0) + COALESCE(down_count, 0)
                     + COALESCE(flat_count, 0)) >= $3
                """
            )
            if snapshot_date is not None:
                row = await conn.fetchrow(
                    f"""
                    SELECT date, market, up_count, down_count, flat_count,
                           limit_up_count, limit_down_count, source, fetched_at
                    FROM market_breadth
                    WHERE market = $1 AND date <= $2
                    {coverage_filter}
                    ORDER BY date DESC
                    LIMIT 1
                    """,
                    market,
                    snapshot_date,
                    *(() if threshold is None else (threshold,)),
                )
            else:
                row = await conn.fetchrow(
                    f"""
                    SELECT date, market, up_count, down_count, flat_count,
                           limit_up_count, limit_down_count, source, fetched_at
                    FROM market_breadth
                    WHERE market = $1
                    {coverage_filter.replace("$3", "$2")}
                    ORDER BY date DESC
                    LIMIT 1
                    """,
                    market,
                    *(() if threshold is None else (threshold,)),
                )
            if row is not None:
                result.append(_row_to_dict(row))
    return result
