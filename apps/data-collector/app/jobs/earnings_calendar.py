"""财报日历（直调 yfinance 库，写入 earnings_calendar）

说明：OpenBB 的 /equity/calendar/earnings 仅 fmp 付费源可用，
因此本 job 在 backend 内直接调 yfinance 库（与 akshare 直调同一先例）。
只覆盖 TRACKED_SYMBOLS 里的美股/港股（A 股 yfinance 无日历数据，akshare
业绩披露接口 stock_yysj_em 因东财改格式解析失败，暂不可用）。
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta
from typing import Any

from app.db import get_pool
from app.constants import TRACKED_SYMBOLS
from app.markets import pick_market, to_yahoo_symbol

logger = logging.getLogger(__name__)

# 只保留今天起未来 90 天的财报日
FUTURE_DAYS = 90
# 防限流：串行 + 每个标的间隔
SLEEP_SECONDS = 0.3


def _fetch_calendar(symbol: str) -> dict[str, Any] | None:
    """同步取 yfinance calendar dict（含 Earnings Date / Earnings Average）。"""
    import yfinance as yf

    try:
        cal = yf.Ticker(to_yahoo_symbol(symbol)).calendar
        return cal if isinstance(cal, dict) else None
    except Exception as e:
        logger.warning(f"yfinance calendar {symbol} failed: {e}")
        return None


async def fetch_and_store_earnings(symbol: str, today: date) -> int:
    """拉单只标的的财报日历，UPSERT 写入。返回写入条数。"""
    cal = await asyncio.to_thread(_fetch_calendar, symbol)
    if not cal:
        return 0

    # 字段因标的而异，全部容错；yfinance 不提供盘前/盘后信息，session 一律 '--'
    dates = cal.get("Earnings Date") or []
    if not isinstance(dates, (list, tuple)):
        dates = [dates]
    eps = cal.get("Earnings Average")
    try:
        eps_estimate = float(eps) if eps is not None else None
    except (TypeError, ValueError):
        eps_estimate = None

    limit = today + timedelta(days=FUTURE_DAYS)
    rows = []
    for d in dates:
        try:
            report_date = d.date() if hasattr(d, "date") else d
        except Exception:
            continue
        if not isinstance(report_date, date):
            continue
        # 只保留未来财报日
        if today <= report_date <= limit:
            rows.append((symbol, report_date, "--", eps_estimate, "yfinance"))
    if not rows:
        return 0

    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.executemany(
            """
            INSERT INTO earnings_calendar
                (symbol, report_date, session, eps_estimate, source, fetched_at)
            VALUES ($1, $2, $3, $4, $5, NOW())
            ON CONFLICT (symbol, report_date) DO UPDATE SET
                session = EXCLUDED.session,
                eps_estimate = EXCLUDED.eps_estimate,
                source = EXCLUDED.source,
                fetched_at = NOW()
            """,
            rows,
        )
    return len(rows)


async def run_earnings_calendar_job() -> int:
    """定时任务：拉 tracked 美股/港股的财报日历（每天一次）"""
    logger.info("=== earnings calendar job start ===")
    today = date.today()
    total = 0
    for symbol in TRACKED_SYMBOLS:
        # A 股 yfinance 无日历数据，跳过（省限流额度）
        if pick_market(symbol) == "CN":
            continue
        total += await fetch_and_store_earnings(symbol, today)
        await asyncio.sleep(SLEEP_SECONDS)

    # 顺手清理过期行（早于昨天），不动未来数据
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM earnings_calendar WHERE report_date < CURRENT_DATE - 1"
        )
    logger.info(f"=== earnings calendar job done: {total} rows ===")
    return total
