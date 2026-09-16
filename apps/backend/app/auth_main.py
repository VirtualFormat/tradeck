"""tradeck auth-api：用户域独立服务入口（/api/auth/* + /health）。

本服务是 tradeck 应用层组件（用户域），与 tradb（行情数据服务）职责分离：
- 只服务 auth（注册 / 登录 / 会话校验 / 登出），不 import 任何行情路由；
- 不碰 DATA_MODE / 数据库身份 marker 校验 / ClickHouse；
- DB 连接走 AUTH_DATABASE_URL（独立 auth-db 小库），与行情库物理隔离。

单 pool 复用设计：auth.py 通过 app.db.get_pool() 取全局连接池。app.db 模块级
只持有「一个」全局 pool（与行情库无关，只是函数名沿用），因此 auth-api 进程里
直接把 settings.DATABASE_URL 指向 AUTH_DATABASE_URL，复用 get_pool/close_pool
既有函数即可——auth.py 零改动。auth-api 与 data-api 是不同进程，互不干扰。
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import auth
from app.config import settings
from app.db import close_pool, get_pool

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# 幂等 schema 初始化 DDL：与 init.sql 末尾 auth 段保持一致（IF NOT EXISTS 兜底，
# 首启自动建表，无需手动迁移；auth-db 是全新空库，无需保留 init.sql 的行情表）。
_SCHEMA_DDL = """
CREATE SCHEMA IF NOT EXISTS auth;

CREATE TABLE IF NOT EXISTS auth.users (
    id BIGSERIAL PRIMARY KEY,
    email TEXT NOT NULL,
    password_hash TEXT NOT NULL,        -- pbkdf2_sha256$... 或 argon2 PHC 串，绝不存明文
    display_name TEXT,
    role TEXT NOT NULL DEFAULT 'user',  -- admin / user（首个注册用户自动 admin）
    status TEXT NOT NULL DEFAULT 'active',  -- active / disabled
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_auth_users_email_lower ON auth.users (lower(email));

CREATE TABLE IF NOT EXISTS auth.sessions (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE,    -- sha256(token) hex
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    last_seen_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_auth_sessions_user_id ON auth.sessions (user_id);
CREATE INDEX IF NOT EXISTS idx_auth_sessions_expires_at ON auth.sessions (expires_at);
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动：连 auth-db 建 pool（单 pool 复用，见模块 docstring）+ 幂等建表；
    关闭：释放连接池。不校验 DATA_MODE/marker，auth-db 无此概念。"""
    logger.info("tradeck auth-api starting...")

    # 单 pool 复用：把 settings.DATABASE_URL 指向 AUTH_DATABASE_URL，
    # 让 app.db.get_pool() 建出的全局 pool 就是 auth 库连接池，auth.py 零改动。
    settings.DATABASE_URL = settings.AUTH_DATABASE_URL

    pool = await get_pool()
    try:
        async with pool.acquire() as conn:
            version = await conn.fetchval("SELECT version()")
            logger.info(f"connected to PostgreSQL: {version[:50]}...")
            await conn.execute(_SCHEMA_DDL)
            logger.info("auth schema initialized (idempotent)")

        logger.info("tradeck auth-api ready")
        yield
    finally:
        logger.info("tradeck auth-api shutting down...")
        await close_pool()


app = FastAPI(title="tradeck auth-api", version="0.1.0", lifespan=lifespan)

# CORS：与 data-api 同款——auth-api 是服务间 API（web BFF 经容器网络调用，
# 消费方走 X-Service-Token 鉴权），默认不放开浏览器跨域（空列表 = CORSMiddleware
# 不放行任何跨域来源，同源/服务端调用不受影响）。确有浏览器直连场景时经
# 环境变量 CORS_ORIGINS（逗号分隔）显式配置。
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)


@app.get("/health")
async def health() -> dict:
    """探活端点（不鉴权，不查库——auth-db 连接状态由 lifespan 保证）。"""
    return {"ok": True}
