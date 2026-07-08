"""公司信息 + 基本面指标 + 财报（调 OpenBB，写入 DB）"""
from __future__ import annotations

import logging

from app.db import get_pool
from app.jobs.daily_kline import TRACKED_SYMBOLS
from app.openbb_client import fetch_openbb

logger = logging.getLogger(__name__)


async def fetch_and_store_profile(symbol: str) -> int:
    """拉公司信息，写入 equity_profiles。"""
    data = await fetch_openbb(
        "/equity/profile",
        {"provider": "yfinance", "symbol": symbol},
    )
    results = data.get("results", [])
    if not results:
        return 0

    r = results[0]
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO equity_profiles (symbol, name, sector, industry, market_cap, currency, exchange, description, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW())
            ON CONFLICT (symbol) DO UPDATE SET
                name = EXCLUDED.name, sector = EXCLUDED.sector,
                industry = EXCLUDED.industry, market_cap = EXCLUDED.market_cap,
                currency = EXCLUDED.currency, exchange = EXCLUDED.exchange,
                description = EXCLUDED.description, updated_at = NOW()
            """,
            symbol,
            r.get("name"),
            r.get("sector"),
            r.get("industry"),
            int(r["market_cap"]) if r.get("market_cap") else None,
            r.get("currency"),
            r.get("exchange"),
            r.get("description"),
        )
    return 1


async def fetch_and_store_metrics(symbol: str) -> int:
    """拉基本面指标，写入 fundamental_metrics。"""
    data = await fetch_openbb(
        "/equity/fundamental/metrics",
        {"provider": "yfinance", "symbol": symbol},
    )
    results = data.get("results", [])
    if not results:
        return 0

    r = results[0]
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO fundamental_metrics (symbol, market_cap, pe_ratio, forward_pe, peg_ratio,
                enterprise_to_ebitda, earnings_growth, revenue_growth, dividend_yield, beta,
                profit_margins, return_on_equity, debt_to_equity, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, NOW())
            ON CONFLICT (symbol) DO UPDATE SET
                market_cap = EXCLUDED.market_cap, pe_ratio = EXCLUDED.pe_ratio,
                forward_pe = EXCLUDED.forward_pe, peg_ratio = EXCLUDED.peg_ratio,
                enterprise_to_ebitda = EXCLUDED.enterprise_to_ebitda,
                earnings_growth = EXCLUDED.earnings_growth,
                revenue_growth = EXCLUDED.revenue_growth,
                dividend_yield = EXCLUDED.dividend_yield, beta = EXCLUDED.beta,
                profit_margins = EXCLUDED.profit_margins,
                return_on_equity = EXCLUDED.return_on_equity,
                debt_to_equity = EXCLUDED.debt_to_equity, updated_at = NOW()
            """,
            symbol,
            int(r["market_cap"]) if r.get("market_cap") else None,
            float(r["pe_ratio"]) if r.get("pe_ratio") else None,
            float(r["forward_pe"]) if r.get("forward_pe") else None,
            float(r["peg_ratio"]) if r.get("peg_ratio") else None,
            float(r["enterprise_to_ebitda"]) if r.get("enterprise_to_ebitda") else None,
            float(r["earnings_growth"]) if r.get("earnings_growth") else None,
            float(r["revenue_growth"]) if r.get("revenue_growth") else None,
            float(r["dividend_yield"]) if r.get("dividend_yield") else None,
            float(r["beta"]) if r.get("beta") else None,
            float(r["profit_margins"]) if r.get("profit_margins") else None,
            float(r["return_on_equity"]) if r.get("return_on_equity") else None,
            float(r["debt_to_equity"]) if r.get("debt_to_equity") else None,
        )
    return 1


async def fetch_and_store_income(symbol: str) -> int:
    """拉财报，写入 income_statements。"""
    data = await fetch_openbb(
        "/equity/fundamental/income",
        {"provider": "sec", "symbol": symbol, "period": "annual", "limit": 3},
    )
    results = data.get("results", [])
    if not results:
        return 0

    pool = await get_pool()
    async with pool.acquire() as conn:
        for r in results:
            fy = r.get("fiscal_year")
            if not fy:
                continue
            await conn.execute(
                """
                INSERT INTO income_statements (symbol, fiscal_year, total_revenue, net_income, gross_profit, operating_income)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (symbol, fiscal_year) DO UPDATE SET
                    total_revenue = EXCLUDED.total_revenue,
                    net_income = EXCLUDED.net_income,
                    gross_profit = EXCLUDED.gross_profit,
                    operating_income = EXCLUDED.operating_income
                """,
                symbol,
                int(fy),
                float(r["total_revenue"]) if r.get("total_revenue") else None,
                float(r["net_income"]) if r.get("net_income") else None,
                float(r["gross_profit"]) if r.get("gross_profit") else None,
                float(r["operating_income"]) if r.get("operating_income") else None,
            )
    return len(results)


async def run_fundamentals_job() -> None:
    """定时任务：拉所有跟踪股票的公司信息 + 指标 + 财报"""
    logger.info("=== fundamentals job start ===")
    total = 0
    for symbol in TRACKED_SYMBOLS:
        total += await fetch_and_store_profile(symbol)
        total += await fetch_and_store_metrics(symbol)
        total += await fetch_and_store_income(symbol)
    logger.info(f"=== fundamentals job done: {total} records ===")
