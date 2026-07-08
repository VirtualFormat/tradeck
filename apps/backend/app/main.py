"""FastAPI 入口 + lifespan（启动 scheduler）"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import historical, indices, movers, quotes
from app.db import close_pool, get_pool
from app.scheduler import start_scheduler, stop_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动：连 DB + 起调度器；关闭：停调度器 + 关 DB"""
    logger.info("tradeck backend starting...")

    # 1. 连 PostgreSQL
    pool = await get_pool()
    async with pool.acquire() as conn:
        version = await conn.fetchval("SELECT version()")
        logger.info(f"connected to PostgreSQL: {version[:50]}...")

    # 2. 启动调度器（会立即触发一次数据拉取）
    await start_scheduler()

    logger.info("tradeck backend ready")
    yield

    # 3. 关闭
    logger.info("tradeck backend shutting down...")
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


@app.get("/health")
async def health():
    return {"status": "ok"}
