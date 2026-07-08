"""APScheduler 定时任务注册"""
from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.jobs.daily_kline import run_daily_kline_job
from app.jobs.fundamentals import run_fundamentals_job
from app.jobs.indices import run_indices_job
from app.jobs.macro import run_macro_job
from app.jobs.movers import run_movers_job
from app.jobs.news import run_news_job
from app.jobs.realtime_quotes import run_realtime_quotes_job

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


async def start_scheduler() -> None:
    """启动调度器 + 立即触发一次所有 job（首次启动）"""
    global _scheduler
    if _scheduler is not None:
        return

    _scheduler = AsyncIOScheduler()

    # 日 K 线：每天 16:00 UTC（美股收盘后）+ 08:00 UTC（A 股收盘后）
    _scheduler.add_job(
        run_daily_kline_job,
        CronTrigger(hour=16, minute=0, timezone="UTC"),
        id="daily_kline_us",
        replace_existing=True,
    )
    _scheduler.add_job(
        run_daily_kline_job,
        CronTrigger(hour=8, minute=0, timezone="UTC"),
        id="daily_kline_cn",
        replace_existing=True,
    )

    # 实时报价：盘中每 30 秒（UTC 13:30-21:00 美股交易时段）
    _scheduler.add_job(
        run_realtime_quotes_job,
        CronTrigger(minute="*/30", timezone="UTC"),
        id="realtime_quotes",
        replace_existing=True,
    )

    # 指数历史：每天 17:00 UTC
    _scheduler.add_job(
        run_indices_job,
        CronTrigger(hour=17, minute=0, timezone="UTC"),
        id="indices",
        replace_existing=True,
    )

    # 涨跌榜：每 5 分钟
    _scheduler.add_job(
        run_movers_job,
        CronTrigger(minute="*/5", timezone="UTC"),
        id="movers",
        replace_existing=True,
    )

    # 新闻：每 30 分钟
    _scheduler.add_job(
        run_news_job,
        CronTrigger(minute="*/30", timezone="UTC"),
        id="news",
        replace_existing=True,
    )

    # 宏观数据：每天 06:00 UTC
    _scheduler.add_job(
        run_macro_job,
        CronTrigger(hour=6, minute=0, timezone="UTC"),
        id="macro",
        replace_existing=True,
    )

    # 财报/公司信息：每周一 07:00 UTC
    _scheduler.add_job(
        run_fundamentals_job,
        CronTrigger(day_of_week="mon", hour=7, minute=0, timezone="UTC"),
        id="fundamentals",
        replace_existing=True,
    )

    _scheduler.start()
    logger.info("Scheduler started")

    # 立即触发一次（首次启动不用等 cron）
    logger.info("=== initial fetch ===")
    await run_indices_job()
    await run_realtime_quotes_job()
    await run_movers_job()
    await run_macro_job()
    await run_news_job()
    await run_fundamentals_job()
    await run_daily_kline_job()
    logger.info("=== initial fetch done ===")


async def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
