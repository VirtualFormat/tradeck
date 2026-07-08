"""GET /api/fundamentals — 从 fundamental_metrics + income_statements 读"""
from __future__ import annotations

from fastapi import APIRouter, Query
from app.db import get_pool

router = APIRouter()


@router.get("/api/fundamentals/metrics")
async def get_metrics(symbol: str = Query(...)):
    """获取基本面指标。"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT symbol, market_cap, pe_ratio, forward_pe, peg_ratio,
                enterprise_to_ebitda, earnings_growth, revenue_growth,
                dividend_yield, beta, profit_margins, return_on_equity,
                debt_to_equity
            FROM fundamental_metrics
            WHERE symbol = $1
            """,
            symbol.upper(),
        )

    if not row:
        return None

    return {
        "symbol": row["symbol"],
        "market_cap": row["market_cap"],
        "pe_ratio": float(row["pe_ratio"]) if row["pe_ratio"] else None,
        "forward_pe": float(row["forward_pe"]) if row["forward_pe"] else None,
        "peg_ratio": float(row["peg_ratio"]) if row["peg_ratio"] else None,
        "enterprise_to_ebitda": float(row["enterprise_to_ebitda"]) if row["enterprise_to_ebitda"] else None,
        "earnings_growth": float(row["earnings_growth"]) if row["earnings_growth"] else None,
        "revenue_growth": float(row["revenue_growth"]) if row["revenue_growth"] else None,
        "dividend_yield": float(row["dividend_yield"]) if row["dividend_yield"] else None,
        "beta": float(row["beta"]) if row["beta"] else None,
        "profit_margins": float(row["profit_margins"]) if row["profit_margins"] else None,
        "return_on_equity": float(row["return_on_equity"]) if row["return_on_equity"] else None,
        "debt_to_equity": float(row["debt_to_equity"]) if row["debt_to_equity"] else None,
        "current_ratio": None,
    }


@router.get("/api/fundamentals/income")
async def get_income(
    symbol: str = Query(...),
    limit: int = Query(3),
):
    """获取利润表。"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT symbol, fiscal_year, total_revenue, net_income, gross_profit, operating_income
            FROM income_statements
            WHERE symbol = $1
            ORDER BY fiscal_year DESC
            LIMIT $2
            """,
            symbol.upper(),
            limit,
        )

    return [
        {
            "fiscal_year": r["fiscal_year"],
            "total_revenue": float(r["total_revenue"]) if r["total_revenue"] else None,
            "net_income": float(r["net_income"]) if r["net_income"] else None,
            "gross_profit": float(r["gross_profit"]) if r["gross_profit"] else None,
            "operating_income": float(r["operating_income"]) if r["operating_income"] else None,
            "research_and_development": None,
            "ebitda": None,
        }
        for r in rows
    ]
