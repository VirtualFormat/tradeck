"""GET /api/technicals — 从 technical_indicators 读；非 tracked 标的从 daily_prices 现算"""
from __future__ import annotations

import pandas as pd
from fastapi import APIRouter, Query

from app.db import get_pool
from app.services.indicators import LOOKBACK_DAYS, compute_indicators

router = APIRouter()


def _f(v) -> float | None:
    return float(v) if v is not None else None


def _r(v) -> float | None:
    """NaN/None → None，其余保留 4 位小数（与 job 口径一致）"""
    if v is None or pd.isna(v):
        return None
    return round(float(v), 4)


@router.get("/api/technicals")
async def get_technicals(
    symbol: str = Query(...),
    days: int = Query(120, ge=1, le=500),
):
    """获取技术指标，按日期升序（方便画图）。返回扁平数组。"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT date, ma5, ma10, ma20, ma60, ema12, ema26,
                   dif, dea, macd, rsi6, rsi14, boll_upper, boll_mid, boll_lower
            FROM technical_indicators
            WHERE symbol = $1
            ORDER BY date DESC
            LIMIT $2
            """,
            symbol.upper(),
            days,
        )

    if rows:
        return [
            {
                "date": r["date"].isoformat() if r["date"] else None,
                "ma5": _f(r["ma5"]),
                "ma10": _f(r["ma10"]),
                "ma20": _f(r["ma20"]),
                "ma60": _f(r["ma60"]),
                "ema12": _f(r["ema12"]),
                "ema26": _f(r["ema26"]),
                "dif": _f(r["dif"]),
                "dea": _f(r["dea"]),
                "macd": _f(r["macd"]),
                "rsi6": _f(r["rsi6"]),
                "rsi14": _f(r["rsi14"]),
                "boll_upper": _f(r["boll_upper"]),
                "boll_mid": _f(r["boll_mid"]),
                "boll_lower": _f(r["boll_lower"]),
            }
            for r in reversed(rows)  # 升序返回
        ]

    # DB 无记录（非 tracked 标的）：从 daily_prices 现算（本地 pandas，无外部调用）
    return await _compute_on_demand(pool, symbol.upper(), days)


async def _compute_on_demand(pool, symbol: str, days: int) -> list[dict]:
    """非 tracked 标的的按需计算：读近 250 天收盘价，本地算指标，返回最近 days 天。"""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT date, close FROM daily_prices
            WHERE symbol = $1 AND close IS NOT NULL
            ORDER BY date DESC
            LIMIT $2
            """,
            symbol,
            LOOKBACK_DAYS,
        )
    if len(rows) < 30:  # 数据太少算不出有效指标
        return []

    closes = pd.Series(
        [float(r["close"]) for r in reversed(rows)],
        index=pd.Index([r["date"] for r in reversed(rows)], name="date"),
        dtype="float64",
    )
    df = compute_indicators(closes).tail(days)
    return [
        {
            "date": idx.isoformat(),
            "ma5": _r(row["ma5"]),
            "ma10": _r(row["ma10"]),
            "ma20": _r(row["ma20"]),
            "ma60": _r(row["ma60"]),
            "ema12": _r(row["ema12"]),
            "ema26": _r(row["ema26"]),
            "dif": _r(row["dif"]),
            "dea": _r(row["dea"]),
            "macd": _r(row["macd"]),
            "rsi6": _r(row["rsi6"]),
            "rsi14": _r(row["rsi14"]),
            "boll_upper": _r(row["boll_upper"]),
            "boll_mid": _r(row["boll_mid"]),
            "boll_lower": _r(row["boll_lower"]),
        }
        for idx, row in df.iterrows()
    ]
