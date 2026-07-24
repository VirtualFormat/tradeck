"""宏观数据日历（FRED via OpenBB → 兜底 akshare 百度财经，写入 economic_calendar）

两源都允许失败：
- FRED 源需 openbb 容器配 FRED_API_KEY，未配置时 OpenBB 返回空 results（正常）
- 百度源（news_economic_baidu）本机 TLS 常被封锁，except 返回空
两源都空 → 写 0 行，正常结束不报错。
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta
from typing import Any

from app.db import get_pool
from app.openbb_client import fetch_openbb

logger = logging.getLogger(__name__)

# FRED 源拉未来 14 天，百度源按天循环未来 7 天
FRED_DAYS = 14
BAIDU_DAYS = 7

# 百度「重要性」星级（数字）→ 文案
_STAR_MAP = {1: "低", 2: "中", 3: "高"}


def _parse_date(v: Any) -> date | None:
    """datetime / ISO 字符串 / date → date 对象（asyncpg 不接受字符串）"""
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10])
    except (ValueError, TypeError):
        return None


def _s(v: Any) -> str | None:
    """任意值 → 字符串（空值/NaN → None）"""
    if v is None:
        return None
    try:
        # pandas NaN 不等于自身
        if v != v:  # noqa: PLR0124
            return None
    except Exception:
        pass
    s = str(v).strip()
    return s or None


async def _fetch_fred(today: date) -> list[tuple]:
    """FRED 源（经 OpenBB /economy/calendar）。返回待写入行，失败/空返回 []。"""
    data = await fetch_openbb(
        "/economy/calendar",
        {
            "provider": "fred",
            "start_date": today.isoformat(),
            "end_date": (today + timedelta(days=FRED_DAYS)).isoformat(),
        },
        timeout=20.0,
    )
    results = data.get("results", [])
    rows = []
    for r in results:
        d = _parse_date(r.get("date"))
        event = _s(r.get("event"))
        if not d or not event:
            continue
        # FRED 的 date 是 datetime，时间部分单独截出来存 event_time
        raw_date = r.get("date")
        event_time = str(raw_date)[11:16] if raw_date and len(str(raw_date)) > 10 else None
        rows.append((
            d,
            event_time,
            _s(r.get("country")) or "",
            event,
            _s(r.get("importance")),
            _s(r.get("actual")),
            _s(r.get("consensus")),
            _s(r.get("previous")),
            "fred",
        ))
    logger.info(f"fred economic calendar: {len(rows)} events")
    return rows


def _fetch_baidu_sync(day: date) -> list[tuple]:
    """同步拉百度财经单日经济数据日历（线程内跑）。"""
    import akshare as ak

    try:
        df = ak.news_economic_baidu(date=day.strftime("%Y%m%d"))
    except Exception as e:
        logger.warning(f"baidu economic calendar {day} failed: {e}")
        return []
    if df is None or df.empty:
        return []

    rows = []
    for _, r in df.iterrows():
        d = _parse_date(r.get("日期"))
        event = _s(r.get("事件"))
        if not d or not event:
            continue
        star = r.get("重要性")
        try:
            importance = _STAR_MAP.get(int(star)) if star == star and star is not None else None
        except (TypeError, ValueError):
            importance = _s(star)
        country = _s(r.get("国家")) or _s(r.get("地区")) or ""
        rows.append((
            d,
            _s(r.get("时间")),
            country,
            event,
            importance,
            _s(r.get("公布")),
            _s(r.get("预期")),
            _s(r.get("前值")),
            "baidu",
        ))
    return rows


async def _fetch_baidu(today: date) -> list[tuple]:
    """百度源：按天循环未来 7 天（直调 akshare，不经 OpenBB）。"""
    rows: list[tuple] = []
    for i in range(BAIDU_DAYS):
        rows.extend(await asyncio.to_thread(_fetch_baidu_sync, today + timedelta(days=i)))
        await asyncio.sleep(0.3)  # 防限流
    logger.info(f"baidu economic calendar: {len(rows)} events")
    return rows


async def run_economic_calendar_job() -> int:
    """定时任务：拉未来两周宏观数据日历（每天一次）。先试 FRED，空则试百度。"""
    logger.info("=== economic calendar job start ===")
    today = date.today()

    rows = await _fetch_fred(today)
    if not rows:
        rows = await _fetch_baidu(today)
    if not rows:
        logger.info("=== economic calendar job done: 0 rows ===")
        return 0

    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.executemany(
            """
            INSERT INTO economic_calendar
                (event_date, event_time, country, event_name, importance,
                 actual, forecast, previous, source, fetched_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, NOW())
            ON CONFLICT (event_date, event_name, country) DO UPDATE SET
                event_time = EXCLUDED.event_time,
                importance = EXCLUDED.importance,
                actual = EXCLUDED.actual,
                forecast = EXCLUDED.forecast,
                previous = EXCLUDED.previous,
                source = EXCLUDED.source,
                fetched_at = NOW()
            """,
            rows,
        )
        # 顺手清理过期行（早于昨天），不动未来数据
        await conn.execute(
            "DELETE FROM economic_calendar WHERE event_date < CURRENT_DATE - 1"
        )
    logger.info(f"=== economic calendar job done: {len(rows)} rows ===")
    return len(rows)
