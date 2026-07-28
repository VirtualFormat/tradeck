"""公司信息 + 基本面指标 + 财报 + 资产负债表 + 现金流量表（调 OpenBB，写入 DB）"""
from __future__ import annotations

import logging
from datetime import date

from app.db import get_pool
from app.jobs.daily_kline import TRACKED_SYMBOLS
from app.markets import to_yahoo_symbol
from app.openbb_client import fetch_openbb

logger = logging.getLogger(__name__)


def _parse_date(s: str | None) -> date | None:
    """ISO 日期字符串 → date，失败返回 None。"""
    if not s:
        return None
    try:
        return date.fromisoformat(str(s)[:10])
    except (ValueError, TypeError):
        return None


async def fetch_and_store_profile(symbol: str) -> int:
    """拉公司信息，写入 equity_profiles。"""
    data = await fetch_openbb(
        "/equity/profile",
        {"provider": "yfinance", "symbol": to_yahoo_symbol(symbol)},
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
        {"provider": "yfinance", "symbol": to_yahoo_symbol(symbol)},
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
            # yfinance dividend_yield 已是百分数（0.32 = 0.32%），统一存小数口径（前端 ×100 显示）
            float(r["dividend_yield"]) / 100 if r.get("dividend_yield") else None,
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
            # SEC 源字段名：total_gross_profit / total_operating_income
            gross = r.get("gross_profit") if r.get("gross_profit") is not None else r.get("total_gross_profit")
            op_income = r.get("operating_income") if r.get("operating_income") is not None else r.get("total_operating_income")
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
                float(gross) if gross is not None else None,
                float(op_income) if op_income is not None else None,
            )
    return len(results)


async def fetch_and_store_balance(symbol: str) -> int:
    """拉资产负债表（年报 limit=5 + 季报 limit=5），写入 balance_sheets。

    注：OpenBB REST 对该端点校验 limit<=5（>5 返回 422），季报只能取 5 期。
    """
    rows = []
    for period, limit in (("annual", 5), ("quarter", 5)):
        data = await fetch_openbb(
            "/equity/fundamental/balance",
            {"provider": "yfinance", "symbol": to_yahoo_symbol(symbol), "period": period, "limit": limit},
        )
        for r in data.get("results", []):
            fiscal_date = _parse_date(r.get("period_ending"))
            if not fiscal_date:
                continue
            # 股东权益：优先含少数股东权益口径，缺失时退普通股权益
            equity = r.get("total_equity_non_controlling_interests")
            if equity is None:
                equity = r.get("common_stock_equity")
            rows.append((
                symbol, period, fiscal_date,
                r.get("total_assets"),
                r.get("total_liabilities_net_minority_interest"),
                equity,
                r.get("total_current_assets"),
                r.get("current_liabilities"),
                r.get("cash_and_cash_equivalents"),
                r.get("inventories"),
                r.get("accounts_receivable"),
                r.get("total_debt"),
                r.get("retained_earnings"),
            ))
    if not rows:
        return 0

    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.executemany(
            """
            INSERT INTO balance_sheets
                (symbol, period, fiscal_date, total_assets, total_liabilities,
                 total_equity, total_current_assets, total_current_liabilities,
                 cash_and_equivalents, inventories, accounts_receivable,
                 total_debt, retained_earnings, fetched_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, NOW())
            ON CONFLICT (symbol, period, fiscal_date) DO UPDATE SET
                total_assets = EXCLUDED.total_assets,
                total_liabilities = EXCLUDED.total_liabilities,
                total_equity = EXCLUDED.total_equity,
                total_current_assets = EXCLUDED.total_current_assets,
                total_current_liabilities = EXCLUDED.total_current_liabilities,
                cash_and_equivalents = EXCLUDED.cash_and_equivalents,
                inventories = EXCLUDED.inventories,
                accounts_receivable = EXCLUDED.accounts_receivable,
                total_debt = EXCLUDED.total_debt,
                retained_earnings = EXCLUDED.retained_earnings,
                fetched_at = NOW()
            """,
            rows,
        )
    return len(rows)


async def fetch_and_store_cash(symbol: str) -> int:
    """拉现金流量表（年报 limit=5 + 季报 limit=5），写入 cash_flow_statements。

    注：OpenBB REST 对该端点校验 limit<=5（>5 返回 422），季报只能取 5 期。
    """
    rows = []
    for period, limit in (("annual", 5), ("quarter", 5)):
        data = await fetch_openbb(
            "/equity/fundamental/cash",
            {"provider": "yfinance", "symbol": to_yahoo_symbol(symbol), "period": period, "limit": limit},
        )
        for r in data.get("results", []):
            fiscal_date = _parse_date(r.get("period_ending"))
            if not fiscal_date:
                continue
            rows.append((
                symbol, period, fiscal_date,
                r.get("operating_cash_flow"),
                r.get("investing_cash_flow"),
                r.get("financing_cash_flow"),
                r.get("capital_expenditure"),
                r.get("free_cash_flow"),
                r.get("net_income_from_continuing_operations"),
                r.get("depreciation_and_amortization"),
                r.get("repurchase_of_capital_stock"),
                r.get("cash_dividends_paid"),
            ))
    if not rows:
        return 0

    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.executemany(
            """
            INSERT INTO cash_flow_statements
                (symbol, period, fiscal_date, operating_cash_flow, investing_cash_flow,
                 financing_cash_flow, capital_expenditure, free_cash_flow, net_income,
                 depreciation_amortization, share_repurchase, dividends_paid, fetched_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, NOW())
            ON CONFLICT (symbol, period, fiscal_date) DO UPDATE SET
                operating_cash_flow = EXCLUDED.operating_cash_flow,
                investing_cash_flow = EXCLUDED.investing_cash_flow,
                financing_cash_flow = EXCLUDED.financing_cash_flow,
                capital_expenditure = EXCLUDED.capital_expenditure,
                free_cash_flow = EXCLUDED.free_cash_flow,
                net_income = EXCLUDED.net_income,
                depreciation_amortization = EXCLUDED.depreciation_amortization,
                share_repurchase = EXCLUDED.share_repurchase,
                dividends_paid = EXCLUDED.dividends_paid,
                fetched_at = NOW()
            """,
            rows,
        )
    return len(rows)


async def run_fundamentals_job() -> None:
    """定时任务：拉所有跟踪股票的公司信息 + 指标 + 财报 + 资产负债表 + 现金流量表"""
    logger.info("=== fundamentals job start ===")
    total = 0
    for symbol in TRACKED_SYMBOLS:
        total += await fetch_and_store_profile(symbol)
        total += await fetch_and_store_metrics(symbol)
        total += await fetch_and_store_income(symbol)
        total += await fetch_and_store_balance(symbol)
        total += await fetch_and_store_cash(symbol)
    logger.info(f"=== fundamentals job done: {total} records ===")
