"""A 股券商研报采集（东财研报，直调 akshare，写入 research_reports）

逐只拉 tracked 30 只 A 股（限速 0.5s/只，防东财封 IP），只留近 90 天。
盈利预测列名随年份动态变化（如「2026-盈利预测-收益」），用正则匹配取最大年份组。
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import date, timedelta
from typing import Any

from app.db import get_pool
from app.jobs.daily_kline import TRACKED_SYMBOLS
from app.markets import pick_market

logger = logging.getLogger(__name__)

KEEP_DAYS = 90  # 只保留近 90 天研报
RATE_LIMIT_DELAY = 0.5  # 每只股票间隔（秒），防东财封 IP

# 盈利预测列名：「2026-盈利预测-收益」/「2026-盈利预测-市盈率」，年份动态变化
_FORECAST_COL_RE = re.compile(r"^(\d{4})-盈利预测-(收益|市盈率)$")


def _f(v: Any) -> float | None:
    try:
        f = float(v) if v is not None else None
    except (TypeError, ValueError):
        return None
    # pandas 缺失值是 NaN，统一转 None
    return None if f is not None and f != f else f


def _parse_date(s: object) -> date | None:
    """东财研报日期格式：2026-07-24"""
    if not s:
        return None
    try:
        return date.fromisoformat(str(s)[:10])
    except (ValueError, TypeError):
        return None


async def fetch_and_store_research_reports(symbol: str, min_date: date) -> int:
    """拉单只 A 股的券商研报（近 90 天），UPSERT。返回写入条数。"""
    import akshare as ak

    code = symbol.split(".")[0]

    def fetch():
        return ak.stock_research_report_em(symbol=code)

    try:
        df = await asyncio.to_thread(fetch)
    except Exception as e:
        logger.warning(f"akshare research reports failed for {symbol}: {e}")
        return 0
    if df is None or df.empty:
        return 0

    # 找盈利预测列的最大年份组（如 2026-盈利预测-收益 / 2026-盈利预测-市盈率）
    forecast_years = [
        int(m.group(1))
        for col in df.columns
        if (m := _FORECAST_COL_RE.match(str(col)))
    ]
    max_year = max(forecast_years) if forecast_years else None
    eps_col = f"{max_year}-盈利预测-收益" if max_year else None
    pe_col = f"{max_year}-盈利预测-市盈率" if max_year else None

    rows = []
    for _, r in df.iterrows():
        title = str(r.get("报告名称") or "").strip()
        publish_date = _parse_date(r.get("日期"))
        if not title or not publish_date or publish_date < min_date:
            continue
        eps = _f(r.get(eps_col)) if eps_col else None
        pe = _f(r.get(pe_col)) if pe_col else None
        rows.append((
            symbol,
            title,
            str(r.get("机构") or "").strip() or None,
            str(r.get("东财评级") or "").strip() or None,
            str(r.get("行业") or "").strip() or None,
            eps,
            pe,
            max_year if (eps is not None or pe is not None) else None,
            publish_date,
            str(r.get("报告PDF链接") or "").strip() or None,
        ))
    if not rows:
        return 0

    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.executemany(
            """
            INSERT INTO research_reports
                (symbol, title, org, rating, industry,
                 eps_forecast, pe_forecast, forecast_year,
                 publish_date, url, fetched_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, NOW())
            ON CONFLICT (symbol, title, publish_date) DO UPDATE SET
                org = EXCLUDED.org,
                rating = EXCLUDED.rating,
                industry = EXCLUDED.industry,
                eps_forecast = EXCLUDED.eps_forecast,
                pe_forecast = EXCLUDED.pe_forecast,
                forecast_year = EXCLUDED.forecast_year,
                url = EXCLUDED.url,
                fetched_at = NOW()
            """,
            rows,
        )
    return len(rows)


async def run_research_reports_job() -> int:
    """定时任务：拉 30 只 A 股跟踪标的的券商研报（限速 0.5s/只）"""
    logger.info("=== research reports job start ===")
    min_date = date.today() - timedelta(days=KEEP_DAYS)
    total = 0
    for symbol in TRACKED_SYMBOLS:
        if pick_market(symbol) != "CN":
            continue
        total += await fetch_and_store_research_reports(symbol, min_date)
        await asyncio.sleep(RATE_LIMIT_DELAY)
    logger.info(f"=== research reports job done: {total} rows ===")
    return total
