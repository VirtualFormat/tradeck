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


@router.get("/api/fundamentals/balance")
async def get_balance(
    symbol: str = Query(...),
    period: str | None = Query(None),
):
    """获取资产负债表（年报+季报）。返回扁平数组，按 fiscal_date 倒序。"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        if period:
            rows = await conn.fetch(
                """
                SELECT symbol, period, fiscal_date, total_assets, total_liabilities,
                    total_equity, total_current_assets, total_current_liabilities,
                    cash_and_equivalents, inventories, accounts_receivable,
                    total_debt, retained_earnings
                FROM balance_sheets
                WHERE symbol = $1 AND period = $2
                ORDER BY fiscal_date DESC
                """,
                symbol.upper(),
                period,
            )
        else:
            rows = await conn.fetch(
                """
                SELECT symbol, period, fiscal_date, total_assets, total_liabilities,
                    total_equity, total_current_assets, total_current_liabilities,
                    cash_and_equivalents, inventories, accounts_receivable,
                    total_debt, retained_earnings
                FROM balance_sheets
                WHERE symbol = $1
                ORDER BY fiscal_date DESC
                """,
                symbol.upper(),
            )

    def _f(v):
        return float(v) if v is not None else None

    return [
        {
            "symbol": r["symbol"],
            "period": r["period"],
            "fiscal_date": r["fiscal_date"].isoformat() if r["fiscal_date"] else None,
            "total_assets": _f(r["total_assets"]),
            "total_liabilities": _f(r["total_liabilities"]),
            "total_equity": _f(r["total_equity"]),
            "total_current_assets": _f(r["total_current_assets"]),
            "total_current_liabilities": _f(r["total_current_liabilities"]),
            "cash_and_equivalents": _f(r["cash_and_equivalents"]),
            "inventories": _f(r["inventories"]),
            "accounts_receivable": _f(r["accounts_receivable"]),
            "total_debt": _f(r["total_debt"]),
            "retained_earnings": _f(r["retained_earnings"]),
        }
        for r in rows
    ]


@router.get("/api/fundamentals/cash")
async def get_cash_flow(
    symbol: str = Query(...),
    period: str | None = Query(None),
):
    """获取现金流量表（年报+季报）。返回扁平数组，按 fiscal_date 倒序。"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        if period:
            rows = await conn.fetch(
                """
                SELECT symbol, period, fiscal_date, operating_cash_flow,
                    investing_cash_flow, financing_cash_flow, capital_expenditure,
                    free_cash_flow, net_income, depreciation_amortization,
                    share_repurchase, dividends_paid
                FROM cash_flow_statements
                WHERE symbol = $1 AND period = $2
                ORDER BY fiscal_date DESC
                """,
                symbol.upper(),
                period,
            )
        else:
            rows = await conn.fetch(
                """
                SELECT symbol, period, fiscal_date, operating_cash_flow,
                    investing_cash_flow, financing_cash_flow, capital_expenditure,
                    free_cash_flow, net_income, depreciation_amortization,
                    share_repurchase, dividends_paid
                FROM cash_flow_statements
                WHERE symbol = $1
                ORDER BY fiscal_date DESC
                """,
                symbol.upper(),
            )

    def _f(v):
        return float(v) if v is not None else None

    return [
        {
            "symbol": r["symbol"],
            "period": r["period"],
            "fiscal_date": r["fiscal_date"].isoformat() if r["fiscal_date"] else None,
            "operating_cash_flow": _f(r["operating_cash_flow"]),
            "investing_cash_flow": _f(r["investing_cash_flow"]),
            "financing_cash_flow": _f(r["financing_cash_flow"]),
            "capital_expenditure": _f(r["capital_expenditure"]),
            "free_cash_flow": _f(r["free_cash_flow"]),
            "net_income": _f(r["net_income"]),
            "depreciation_amortization": _f(r["depreciation_amortization"]),
            "share_repurchase": _f(r["share_repurchase"]),
            "dividends_paid": _f(r["dividends_paid"]),
        }
        for r in rows
    ]
