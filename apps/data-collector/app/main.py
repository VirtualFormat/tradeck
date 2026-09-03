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

# 同花顺全市场公司行为事件 + 本地日频复权因子。init.sql 仅空卷执行，
# prod 存量卷需要启动迁移；IF NOT EXISTS 幂等。
_CORPORATE_ACTION_MIGRATION = """
CREATE TABLE IF NOT EXISTS corporate_action_events (
    symbol VARCHAR(20) NOT NULL,
    ex_date DATE NOT NULL,
    dividend_per_share NUMERIC(20,8) NOT NULL DEFAULT 0,
    per_share_bonus NUMERIC(20,8) NOT NULL DEFAULT 0,
    allotment_ratio NUMERIC(20,8) NOT NULL DEFAULT 0,
    allotment_price NUMERIC(20,8) NOT NULL DEFAULT 0,
    currency VARCHAR(8) NOT NULL DEFAULT 'CNY',
    source VARCHAR(20) NOT NULL DEFAULT 'hithink',
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (symbol, ex_date)
);
CREATE INDEX IF NOT EXISTS idx_corporate_events_date
    ON corporate_action_events(ex_date DESC);
"""

# 自有 data pool 元数据热层。findb 是初始化来源，供应商原始包不长期保留。
# init.sql 只在空卷执行，存量卷需补表。
_FINDB_METADATA_MIGRATION = """
CREATE TABLE IF NOT EXISTS instrument_master (
    symbol VARCHAR(32) NOT NULL,
    name TEXT,
    asset VARCHAR(32),
    market VARCHAR(16),
    security_type VARCHAR(64),
    source VARCHAR(32) NOT NULL,
    source_updated_at TIMESTAMP,
    PRIMARY KEY (symbol, source)
);
CREATE INDEX IF NOT EXISTS idx_instrument_master_asset_market
    ON instrument_master(asset, market);
CREATE TABLE IF NOT EXISTS data_coverage (
    symbol VARCHAR(32) NOT NULL,
    frequency VARCHAR(16) NOT NULL,
    start_at TIMESTAMP,
    end_at TIMESTAMP,
    row_count BIGINT,
    source VARCHAR(32) NOT NULL,
    source_updated_at TIMESTAMP,
    PRIMARY KEY (symbol, frequency, source)
);
CREATE INDEX IF NOT EXISTS idx_data_coverage_frequency_end
    ON data_coverage(frequency, end_at DESC);
CREATE TABLE IF NOT EXISTS instrument_name_history (
    symbol VARCHAR(32), name TEXT, start_date DATE, end_date DATE,
    ann_date DATE, change_reason TEXT, source VARCHAR(32) NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_instrument_name_history_symbol_date
    ON instrument_name_history(symbol, start_date DESC);
CREATE TABLE IF NOT EXISTS trading_suspensions (
    symbol VARCHAR(32), trade_date DATE, suspend_timing TEXT,
    suspend_type VARCHAR(32), source VARCHAR(32) NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_trading_suspensions_symbol_date
    ON trading_suspensions(symbol, trade_date DESC);
CREATE TABLE IF NOT EXISTS data_pool_state (
    module VARCHAR(32) PRIMARY KEY,
    source VARCHAR(32) NOT NULL,
    tier VARCHAR(16) NOT NULL,
    built_at TIMESTAMPTZ,
    sha256 CHAR(64) NOT NULL,
    local_path TEXT NOT NULL,
    row_counts JSONB NOT NULL DEFAULT '{}'::jsonb,
    synced_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动：连 DB、校验数据库身份并按模式起调度器；关闭：停调度器、释放连接池。"""
    logger.info("tradb data-collector starting in %s mode...", settings.DATA_MODE)

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
            await conn.execute(_CORPORATE_ACTION_MIGRATION)
            await conn.execute(_FINDB_METADATA_MIGRATION)
            logger.info(f"connected to PostgreSQL: {version[:50]}...")
            logger.info("database DATA_MODE marker verified: %s", database_mode)

        if settings.DATA_MODE == "mock":
            # live/mock 互斥：mock 模式不起调度器；seed 不在 collector 职责内。
            logger.info("DATA_MODE=mock: scheduler and live data jobs are disabled")
        else:
            # live 模式只运行真实数据管道，启动时会后台触发一轮预热。
            await start_scheduler()
            scheduler_started = True

        logger.info("tradb data-collector ready")
        yield
    finally:
        logger.info("tradb data-collector shutting down...")
        if scheduler_started:
            await stop_scheduler()
        # AmazingData/tgw 跑在独立 native worker；显式回收，避免单点登录会话
        # 在 collector 优雅退出后继续占用。
        from app.datasource.amazingdata_source import shutdown as shutdown_amazingdata

        await shutdown_amazingdata()
        await close_pool()


app = FastAPI(title="tradb data-collector", version="0.1.0", lifespan=lifespan)

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
