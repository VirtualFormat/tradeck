"""GET /api/analyst — 从 analyst_consensus 读；无数据时经 collector 按需回源"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Query

from app.api._ensure import ensure, valid_symbol
from app.db import get_pool

router = APIRouter()


def _parse_as_of(as_of: str | None) -> date | None:
    """解析 as_of 查询参数（YYYY-MM-DD）；格式非法时返回 None，优雅降级为最新快照。"""
    if not as_of:
        return None
    try:
        return date.fromisoformat(as_of)
    except ValueError:
        return None


async def _fetch_row(pool, symbol: str, as_of: date | None = None):
    async with pool.acquire() as conn:
        if as_of is not None:
            # as-of：取该日期前最近一条日快照（point-in-time）
            return await conn.fetchrow(
                """
                SELECT symbol, snapshot_date, recommendation, recommendation_mean,
                    number_of_analysts, target_high, target_low, target_consensus,
                    target_median, current_price, currency
                FROM analyst_consensus
                WHERE symbol = $1 AND snapshot_date <= $2
                ORDER BY snapshot_date DESC
                LIMIT 1
                """,
                symbol,
                as_of,
            )
        return await conn.fetchrow(
            """
            SELECT symbol, snapshot_date, recommendation, recommendation_mean,
                number_of_analysts, target_high, target_low, target_consensus,
                target_median, current_price, currency
            FROM analyst_consensus
            WHERE symbol = $1
            ORDER BY snapshot_date DESC
            LIMIT 1
            """,
            symbol,
        )


@router.get("/api/analyst/consensus")
async def get_consensus(
    symbol: str = Query(...),
    as_of: str | None = Query(None),
):
    """获取分析师共识/目标价。默认取最新快照；传 as_of（YYYY-MM-DD）取该日期前最近一条。

    as_of 格式非法时优雅降级为最新快照；as_of 路径不触发按需回源
    （回源拿到的是「现在」的值，对历史时点无意义且违背 point-in-time 语义）。
    """
    sym = symbol.upper()
    as_of_date = _parse_as_of(as_of)
    pool = await get_pool()
    row = await _fetch_row(pool, sym, as_of_date)
    if not row and as_of_date is None and valid_symbol(sym):
        await ensure("consensus", [sym])
        row = await _fetch_row(pool, sym)

    if not row:
        return None

    def _f(v):
        return float(v) if v is not None else None

    return {
        "symbol": row["symbol"],
        "snapshot_date": row["snapshot_date"].isoformat() if row["snapshot_date"] else None,
        "recommendation": row["recommendation"],
        "recommendation_mean": _f(row["recommendation_mean"]),
        "number_of_analysts": row["number_of_analysts"],
        "target_high": _f(row["target_high"]),
        "target_low": _f(row["target_low"]),
        "target_consensus": _f(row["target_consensus"]),
        "target_median": _f(row["target_median"]),
        "current_price": _f(row["current_price"]),
        "currency": row["currency"],
        # 日快照表（PK symbol+snapshot_date），as_of 是精确的 point-in-time
        "as_of_exact": True,
    }
