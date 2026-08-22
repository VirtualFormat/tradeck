"""A 股公告采集（东财全市场公告，直调 akshare，写入 announcements）

一次调用拿单日全市场公告（约 1500 行/天），本地过滤 tracked 30 只 A 股。
当天无数据则试前一自然日；周末/节假日自然为空（0 行正常结束）。
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

from app.datasource import call_akshare
from app.db import get_pool
from app.constants import TRACKED_SYMBOLS
from app.markets import pick_market

logger = logging.getLogger(__name__)

# tracked A 股：东财代码（去后缀，如 600519）→ 内部 symbol（如 600519.SS）
_CN_CODE_MAP = {
    s.split(".")[0]: s for s in TRACKED_SYMBOLS if pick_market(s) == "CN"
}


def _parse_date(s: object) -> date | None:
    """东财公告日期格式：2026-07-24"""
    if not s:
        return None
    try:
        return date.fromisoformat(str(s)[:10])
    except (ValueError, TypeError):
        return None


async def _fetch_day(day: date) -> list[tuple]:
    """拉单日全市场公告，过滤 tracked A 股，返回待写行。"""
    import akshare as ak

    date_str = day.strftime("%Y%m%d")

    def fetch():
        return ak.stock_notice_report(symbol="全部", date=date_str)

    try:
        df = await call_akshare(fetch)
    except Exception as e:
        logger.warning(f"akshare announcements failed for {date_str}: {e}")
        return []
    if df is None or df.empty:
        return []

    rows = []
    for _, r in df.iterrows():
        code = str(r.get("代码") or "").strip()
        symbol = _CN_CODE_MAP.get(code)
        if not symbol:
            continue
        title = str(r.get("公告标题") or "").strip()
        publish_date = _parse_date(r.get("公告日期"))
        if not title or not publish_date:
            continue
        rows.append((
            symbol,
            title,
            str(r.get("公告类型") or "").strip() or None,
            publish_date,
            str(r.get("网址") or "").strip() or None,
        ))
    return rows


async def run_announcements_job() -> int:
    """定时任务：拉 tracked A 股公告（当天为空则试前一自然日）"""
    logger.info("=== announcements job start ===")
    today = date.today()
    rows = await _fetch_day(today)
    if not rows:
        yesterday = today - timedelta(days=1)
        rows = await _fetch_day(yesterday)
    if not rows:
        logger.info("=== announcements job done: 0 rows ===")
        return 0

    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.executemany(
            """
            INSERT INTO announcements
                (symbol, title, category, publish_date, url, fetched_at)
            VALUES ($1, $2, $3, $4, $5, NOW())
            ON CONFLICT (symbol, title, publish_date) DO UPDATE SET
                category = EXCLUDED.category,
                url = EXCLUDED.url,
                fetched_at = NOW()
            """,
            rows,
        )
    logger.info(f"=== announcements job done: {len(rows)} rows ===")
    return len(rows)
