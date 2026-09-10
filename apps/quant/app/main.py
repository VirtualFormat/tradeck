"""quant HTTP 服务入口（uvicorn app.main:app，单进程纪律）。

K1：lifespan 内挂 AsyncIOScheduler，注册每日信号 cron；与 api.py 的
@app.on_event("startup") 共存——starlette 下自定义 lifespan 会接管 on_event
钩子，故迁移逻辑在此 import 后显式调用一次（不重复迁移）。
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.api import _startup as _migrate_strategy_dirs
from app.api import app
from app.config import settings
from app.jobs import daily_signals_job

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

# 每日信号 cron 时间：22:30 UTC —— A 股 15:00 收盘（07:00 UTC）、
# 美股常规时段 16:00 ET 收盘（夏令 20:00 / 冬令 21:00 UTC），22:30 UTC
# 落在两市场收盘之后，日K 增量任务（A/港 08:30、美股 21:30 UTC）也已跑完。
_DAILY_SIGNALS_CRON = {"hour": 22, "minute": 30}


@asynccontextmanager
async def lifespan(app_):  # noqa: ARG001 — ASGI 协议要求签名带 app
    # starlette：自定义 lifespan 时 @app.on_event("startup") 不再自动执行，
    # 这里显式调用 api.py 原迁移逻辑（其内部幂等），保证行为一致、不重复注册。
    _migrate_strategy_dirs()
    scheduler = AsyncIOScheduler(timezone="UTC")
    if settings.QUANT_SIGNAL_ENABLED:
        scheduler.add_job(
            daily_signals_job,  # 模块级 async def（已知坑#7）
            CronTrigger(**_DAILY_SIGNALS_CRON, timezone="UTC"),
            id="daily_signals",
            name="每日信号扫描",
            replace_existing=True,
            max_instances=1,
        )
        logger.info("每日信号 cron 已注册：22:30 UTC")
    else:
        logger.info("QUANT_SIGNAL_ENABLED=false，每日信号 cron 未注册")
    scheduler.start()
    try:
        yield
    finally:
        scheduler.shutdown(wait=False)


app.router.lifespan_context = lifespan

__all__ = ["app"]
