"""用户登录 P0：/api/auth/*（注册 / 登录 / 会话校验 / 登出）。

数据存独立 PG schema auth（见 init.sql）；库中只存密码哈希与 token 的
sha256，明文 token 仅登录响应返回一次。

鉴权：与全站一致挂 read_access（service token），web BFF 作为消费方调用。
限流：login/register 按 IP+email 进程内计数，10 分钟窗口内 >=10 次拒绝 429。
注意是单进程内存语义（与 data-api 单进程运行的既有约定一致），多实例部署后
需升级为共享存储（如 Redis / PG 计数表）。
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import secrets
import time
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.api._service_auth import read_access
from app.auth_security import hash_password, verify_password
from app.config import settings
from app.db import get_pool

logger = logging.getLogger(__name__)

# 全文件统一挂 read_access（配置 SERVICE_TOKENS 后强制 X-Service-Token）
router = APIRouter(dependencies=[Depends(read_access)])

# ---- 限流（进程内，单进程语义）----
_RATE_WINDOW_SECONDS = 600  # 10 分钟窗口
_RATE_MAX_FAILURES = 10
# 失败计数表上限：超过即触发整体淘汰，防字典无界增长
_FAILURE_TABLE_MAX_SIZE = 10_000
# (ip, email) -> (窗口起点 monotonic, 失败次数)
_failure_counts: dict[tuple[str, str], tuple[float, int]] = {}


def _client_ip(request: Request) -> str:
    """提取真实客户端 IP。可信链只有 web BFF 一跳，XFF 由 BFF 注入真实客户端 IP，
    故优先取 X-Forwarded-For 最左一个；取不到回退对端地址（即 BFF）。"""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        first = xff.split(",", 1)[0].strip()
        if first:
            return first
    return request.client.host if request.client else "unknown"


def _rate_limit_key(request: Request, email: str) -> tuple[str, str]:
    return _client_ip(request), email.lower()


def _check_rate_limit(key: tuple[str, str]) -> None:
    """窗口内失败次数已达上限则 429。"""
    now = time.monotonic()
    window_start, count = _failure_counts.get(key, (now, 0))
    if now - window_start > _RATE_WINDOW_SECONDS:
        return
    if count >= _RATE_MAX_FAILURES:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="失败次数过多，请 10 分钟后再试",
        )


def _record_failure(key: tuple[str, str]) -> None:
    now = time.monotonic()
    if len(_failure_counts) >= _FAILURE_TABLE_MAX_SIZE:
        # 先淘汰窗口已过的条目；仍超限则全清重来——粗粒度兜底，
        # 宁可误清导致限流窗口重置，也不可撑爆内存
        expired = [
            k
            for k, (window_start, _count) in _failure_counts.items()
            if now - window_start > _RATE_WINDOW_SECONDS
        ]
        for k in expired:
            del _failure_counts[k]
        if len(_failure_counts) >= _FAILURE_TABLE_MAX_SIZE:
            _failure_counts.clear()
    window_start, count = _failure_counts.get(key, (now, 0))
    if now - window_start > _RATE_WINDOW_SECONDS:
        _failure_counts[key] = (now, 1)
    else:
        _failure_counts[key] = (window_start, count + 1)


def _clear_failures(key: tuple[str, str]) -> None:
    _failure_counts.pop(key, None)


# ---- 请求模型 ----


# 邮箱格式底线：恰好一个 @、两端非空、无空白。
# 内部部署允许无点号域名（如 best@thu），故不做域名级校验（放弃 EmailStr）。
_EMAIL_SHAPE = re.compile(r"^[^@\s]+@[^@\s]+$")


def _check_email_shape(value: str) -> str:
    # str_strip_whitespace 已先行 strip；此处仍兜底 strip，防直接构造模型绕过
    value = value.strip()
    if not _EMAIL_SHAPE.match(value):
        raise ValueError("邮箱格式无效")
    return value


class RegisterRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    email: str
    # P0 内测期放宽到 6 位；P1 改密功能上线后回收到 8
    password: str = Field(min_length=6)
    display_name: str | None = None
    invite_token: str | None = None

    _validate_email = field_validator("email")(_check_email_shape)


class LoginRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    email: str
    password: str = Field(min_length=1)

    _validate_email = field_validator("email")(_check_email_shape)


class LogoutRequest(BaseModel):
    token: str = Field(min_length=1)


# ---- 内部工具 ----


def _sha256_hex(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _user_payload(row) -> dict:
    return {
        "id": row["id"],
        "email": row["email"],
        "display_name": row["display_name"],
        "role": row["role"],
    }


async def _touch_last_seen(session_id: int) -> None:
    """fire-and-forget 更新 last_seen_at；失败丢弃，不影响会话校验请求。"""
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE auth.sessions SET last_seen_at = now() WHERE id = $1",
                session_id,
            )
    except Exception:
        logger.warning("session last_seen_at 更新失败（丢弃）id=%s", session_id)


# ---- 端点 ----


@router.post("/api/auth/register", status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest, request: Request):
    """邮箱注册。配置 AUTH_INVITE_CODE 时必须携带匹配的 invite_token；
    库中首个用户自动 role='admin'；email 不区分大小写去重（lower 唯一索引）。"""
    # 邮箱归一化：与登录查询（lower 比对）、限流 key 三方对齐
    email = body.email.strip().lower()
    key = _rate_limit_key(request, email)
    _check_rate_limit(key)

    if settings.AUTH_INVITE_CODE:
        if not body.invite_token or not secrets.compare_digest(
            body.invite_token, settings.AUTH_INVITE_CODE
        ):
            _record_failure(key)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="邀请码无效",
            )

    password_hash = hash_password(body.password)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            # 库中用户数==0 时首个注册用户自动成为管理员
            user_count = await conn.fetchval("SELECT count(*) FROM auth.users")
            role = "admin" if user_count == 0 else "user"
            try:
                row = await conn.fetchrow(
                    """
                    INSERT INTO auth.users (email, password_hash, display_name, role)
                    VALUES ($1, $2, $3, $4)
                    RETURNING id, email, display_name, role
                    """,
                    email,
                    password_hash,
                    body.display_name,
                    role,
                )
            except Exception as exc:
                # lower(email) 唯一索引冲突 → 邮箱已注册
                if exc.__class__.__name__ == "UniqueViolationError":
                    _record_failure(key)
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="该邮箱已注册",
                    ) from exc
                raise
    _clear_failures(key)
    return {"user": _user_payload(row)}


@router.post("/api/auth/login")
async def login(body: LoginRequest, request: Request):
    """邮箱+密码登录。失败一律 401「邮箱或密码错误」（不区分哪个错，防账号枚举）。

    成功创建 session：明文 token = secrets.token_urlsafe(32)，库中只存 sha256，
    过期时间 now() + AUTH_SESSION_DAYS 天。
    """
    key = _rate_limit_key(request, body.email)
    _check_rate_limit(key)

    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, email, display_name, role, status, password_hash
            FROM auth.users
            WHERE lower(email) = lower($1)
            """,
            body.email,
        )

    if (
        row is None
        or row["status"] != "active"
        or not verify_password(row["password_hash"], body.password)
    ):
        _record_failure(key)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="邮箱或密码错误",
        )

    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.AUTH_SESSION_DAYS)
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO auth.sessions (user_id, token_hash, expires_at, last_seen_at)
            VALUES ($1, $2, $3, now())
            """,
            row["id"],
            _sha256_hex(token),
            expires_at,
        )
    _clear_failures(key)
    return {
        "token": token,
        "expires_at": expires_at.isoformat(),
        "user": _user_payload(row),
    }


@router.post("/api/auth/session")
async def get_session(token: str = Header(..., min_length=1, alias="X-Session-Token")):
    """会话校验（供 web middleware/server 调用）。POST + X-Session-Token 头传
    token（避免 GET query string 进 access log）。命中且未过期、用户 active
    则返回用户信息并异步更新 last_seen_at；否则 401。

    顺手清理已过期 session（低频调用，无需专门优化）。
    """
    token_hash = _sha256_hex(token)
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT s.id AS session_id, s.expires_at,
                   u.id, u.email, u.display_name, u.role, u.status
            FROM auth.sessions s
            JOIN auth.users u ON u.id = s.user_id
            WHERE s.token_hash = $1
            """,
            token_hash,
        )
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="会话无效或已过期",
            )
        now = datetime.now(timezone.utc)
        if row["expires_at"] <= now or row["status"] != "active":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="会话无效或已过期",
            )
        # 顺手清理已过期会话（限定批量，避免大表全扫）
        await conn.execute(
            """
            DELETE FROM auth.sessions
            WHERE id IN (
                SELECT id FROM auth.sessions WHERE expires_at < now() LIMIT 100
            )
            """
        )
    # fire-and-forget 更新 last_seen_at（不阻塞响应）
    asyncio.create_task(_touch_last_seen(row["session_id"]))
    return {
        "user": _user_payload(row),
        "expires_at": row["expires_at"].isoformat(),
    }


@router.post("/api/auth/logout")
async def logout(body: LogoutRequest):
    """登出：删除对应 session。幂等——token 不存在也返回 ok。"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM auth.sessions WHERE token_hash = $1",
            _sha256_hex(body.token),
        )
    return {"ok": True}
