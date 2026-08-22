"""data-collector FastAPI 入口 + lifespan。

collector 是唯一写者：连 DB、校验 DATA_MODE 身份、按 live/mock 互斥
启动调度器。只暴露 /health、/api/system 运维路由（任务状态/手动触发）
与 /api/ondemand 按需回源入口（data-api 读路由在 DB 无数据时经 HTTP 调用），
不注册任何业务读路由。mock 模式下不起 scheduler；collector
本身不执行 mock seed（身份契约见 docs/DATA-SERVICE.md 与 TASKS 阶段二 2.3）。
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import ondemand, system
from app.config import settings
from app.database_mode import ensure_database_mode
from app.db import close_pool, get_pool
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

# 数据质量层两表（init.sql 只在空卷执行；存量卷需就地建表）。
_DATA_QUALITY_MIGRATION = """
CREATE TABLE IF NOT EXISTS data_quality_rejects (
    id BIGSERIAL PRIMARY KEY,
    source_table VARCHAR(50) NOT NULL,
    symbol VARCHAR(20),
    raw_payload JSONB NOT NULL,
    reject_reason TEXT NOT NULL,
    severity VARCHAR(4) NOT NULL,
    rejected_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_dq_rejects_table_time
    ON data_quality_rejects(source_table, rejected_at DESC);
CREATE TABLE IF NOT EXISTS data_quality_metrics (
    table_name VARCHAR(50) NOT NULL,
    date DATE NOT NULL,
    total INT NOT NULL DEFAULT 0,
    accepted INT NOT NULL DEFAULT 0,
    rejected INT NOT NULL DEFAULT 0,
    repaired INT NOT NULL DEFAULT 0,
    quality_score NUMERIC(6,4),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (table_name, date)
);
CREATE INDEX IF NOT EXISTS idx_dq_metrics_date ON data_quality_metrics(date DESC);
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动：连 DB、校验数据库身份并按模式起调度器；关闭：停调度器、释放连接池。"""
    logger.info("tradeck data-collector starting in %s mode...", settings.DATA_MODE)

    # 1. 连 PostgreSQL，并在 scheduler 启动前校验数据库身份（与 backend 共享同一 marker）。
    pool = await get_pool()
    scheduler_started = False
    try:
        async with pool.acquire() as conn:
            version = await conn.fetchval("SELECT version()")
            database_mode = await ensure_database_mode(conn, settings.DATA_MODE)
            # init.sql 只在空卷执行；存量卷必须在任何 job 前补齐字段。
            await conn.execute(_QUOTE_DATA_AS_OF_MIGRATION)
            await conn.execute(_DATA_QUALITY_MIGRATION)
            logger.info(f"connected to PostgreSQL: {version[:50]}...")
            logger.info("database DATA_MODE marker verified: %s", database_mode)

        if settings.DATA_MODE == "mock":
            # live/mock 互斥：mock 模式不起调度器；seed 不在 collector 职责内。
            logger.info("DATA_MODE=mock: scheduler and live data jobs are disabled")
        else:
            # live 模式只运行真实数据管道，启动时会后台触发一轮预热。
            await start_scheduler()
            scheduler_started = True

        logger.info("tradeck data-collector ready")
        yield
    finally:
        logger.info("tradeck data-collector shutting down...")
        if scheduler_started:
            await stop_scheduler()
        await close_pool()


app = FastAPI(title="tradeck data-collector", version="0.1.0", lifespan=lifespan)

# CORS（collector 只被内部运维入口访问，与 backend 保持一致的宽松策略）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 只注册运维路由：任务状态 / 手动触发；业务读路由全部留在 data-api。
# ondemand 是唯一写者侧的按需回源入口（data-api 经 HTTP 调用，见 api/ondemand.py）。
app.include_router(system.router)
app.include_router(ondemand.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
