"""FastAPI 入口 + lifespan（按 DATA_MODE 启动 live 管道或 mock 数据）。"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import analyst, boards, calendar, cn_extras, cross_asset, fundflow, fundamentals, historical, indices, macro, market_summary, movers, news, profile, quotes, search, system, technicals
from app.config import settings
from app.db import close_pool, get_pool
from app.mock_data import ensure_database_mode
from app.scheduler import start_scheduler, stop_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

_QUOTE_DATA_AS_OF_MIGRATION = """
ALTER TABLE quote_snapshots
ADD COLUMN IF NOT EXISTS data_as_of TIMESTAMPTZ
"""


async def _skip_mock_on_demand_fetch(
    key: str, fetch: object  # noqa: ARG001 — 与 _ensure.ensure 签名兼容
) -> None:
    """mock 模式不执行读 API 的真实数据按需回源。"""
    logger.info("DATA_MODE=mock: skipped on-demand live fetch: %s", key)


if settings.DATA_MODE == "mock":
    # 各路由在模块导入时复制 ensure 引用，因此在注册路由前统一替换入口。
    analyst.ensure = _skip_mock_on_demand_fetch
    fundamentals.ensure = _skip_mock_on_demand_fetch
    profile.ensure = _skip_mock_on_demand_fetch
    quotes.ensure = _skip_mock_on_demand_fetch


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动：连 DB，并按 live/mock 互斥运行；关闭：释放对应资源。"""
    logger.info("tradeck backend starting in %s mode...", settings.DATA_MODE)

    # 1. 连 PostgreSQL，并在任何 seed/scheduler 前校验数据库身份。
    pool = await get_pool()
    scheduler_started = False
    try:
        async with pool.acquire() as conn:
            version = await conn.fetchval("SELECT version()")
            database_mode = await ensure_database_mode(conn, settings.DATA_MODE)
            # init.sql 只在空卷执行；存量卷必须在任何 seed/job 前补齐字段。
            await conn.execute(_QUOTE_DATA_AS_OF_MIGRATION)
            logger.info(f"connected to PostgreSQL: {version[:50]}...")
            logger.info("database DATA_MODE marker verified: %s", database_mode)

        if settings.DATA_MODE == "mock":
            from app.seed_mock import run_seed

            async with pool.acquire() as conn:
                counts = await run_seed(conn)
            logger.info("DATA_MODE=mock: seeded %s rows", sum(counts.values()))
            logger.info("DATA_MODE=mock: scheduler and live data jobs are disabled")
        else:
            # live 模式只运行真实数据管道，启动时会后台触发一轮预热。
            await start_scheduler()
            scheduler_started = True

        logger.info("tradeck backend ready")
        yield
    finally:
        logger.info("tradeck backend shutting down...")
        if scheduler_started:
            await stop_scheduler()
        await close_pool()


app = FastAPI(title="tradeck backend", version="0.1.0", lifespan=lifespan)

# CORS（前端同源访问不需要，但 dev 环境跨端口要）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(quotes.router)
app.include_router(historical.router)
app.include_router(indices.router)
app.include_router(movers.router)
app.include_router(news.router)
app.include_router(macro.router)
app.include_router(profile.router)
app.include_router(fundamentals.router)
app.include_router(analyst.router)
app.include_router(system.router)
app.include_router(search.router)
app.include_router(boards.router)
app.include_router(fundflow.router)
app.include_router(technicals.router)
app.include_router(calendar.router)
app.include_router(cn_extras.router)
app.include_router(cross_asset.router)
app.include_router(market_summary.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
