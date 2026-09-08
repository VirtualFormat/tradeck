"""data-api（原 backend）FastAPI 入口 + lifespan。

拆分后职责：唯一读出口，只暴露 18 个业务读路由，从库读数据（<50ms）。
- 不起 scheduler、不写库（写路径全部收敛在 data-collector，单一写者）。
- 不 seed（mock 数据准备属独立流程，见 docs/TASKS-DATA-SERVICE.md 阶段二 2.3）。
- DATA_MODE 仅用于：mock 模式下关闭「读 API 按需回源」（不触发真实数据回源）。
数据库身份 marker 由 collector 绑定；data-api 启动时只校验一致性，不匹配 fail fast。
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import analyst, bars, bars_minute, boards, calendar, cn_extras, cross_asset, fundflow, fundamentals, historical, indices, macro, market_summary, minute_bars, movers, news, profile, quotes, search, system, technicals
from app.config import settings
from app.database_mode import ensure_database_mode
from app.db import close_pool, get_pool

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def _skip_mock_on_demand_fetch(
    kind: str, symbols: list[str]  # noqa: ARG001 — 与 _ensure.ensure 签名兼容
) -> None:
    """mock 模式不执行读 API 的真实数据按需回源（不发起 collector 调用）。"""
    logger.info("DATA_MODE=mock: skipped on-demand live fetch: %s:%s", kind, symbols)


if settings.DATA_MODE == "mock":
    # 各路由在模块导入时复制 ensure 引用，因此在注册路由前统一替换入口。
    analyst.ensure = _skip_mock_on_demand_fetch
    fundamentals.ensure = _skip_mock_on_demand_fetch
    profile.ensure = _skip_mock_on_demand_fetch
    quotes.ensure = _skip_mock_on_demand_fetch


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动：连 DB 并校验数据库身份（不绑定、不写库）；关闭：释放连接池。"""
    logger.info("tradb data-api starting in %s mode...", settings.DATA_MODE)

    pool = await get_pool()
    try:
        async with pool.acquire() as conn:
            version = await conn.fetchval("SELECT version()")
            database_mode = await ensure_database_mode(conn, settings.DATA_MODE)
            logger.info(f"connected to PostgreSQL: {version[:50]}...")
            logger.info("database DATA_MODE marker verified: %s", database_mode)

        logger.info("tradb data-api ready")
        yield
    finally:
        logger.info("tradb data-api shutting down...")
        await close_pool()


app = FastAPI(title="tradb data-api", version="0.1.0", lifespan=lifespan)

# CORS：data-api 是服务间 API（消费方经 X-Service-Token 鉴权），默认不放开
# 浏览器跨域（空列表 = CORSMiddleware 不放行任何跨域来源，同源/服务端调用
# 不受影响）。确有浏览器直连场景时经环境变量 CORS_ORIGINS（逗号分隔）显式配置。
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()],
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
app.include_router(bars.router)
app.include_router(minute_bars.router)
app.include_router(bars_minute.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
