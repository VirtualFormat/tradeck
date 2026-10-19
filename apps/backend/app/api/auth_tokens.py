"""个人访问令牌 PAT：/api/auth/tokens*（签发 / 列表 / 撤销 / mcp 校验）。

设计见 docs/MCP.md「P1 个人访问令牌」：
- 令牌 = "tdk_pat_" + secrets.token_urlsafe(32)；固定前缀便于密钥扫描识别、与
  session token 区分。库里只存 sha256 hex（与 auth.sessions 同口径），明文仅
  签发响应返回一次；token_prefix（前 12 字符）仅供展示。
- 管理端点（签发/列表/撤销）用 X-Session-Token 识别当前用户，校验逻辑复用
  auth.validate_session（session 未过期 + users.status=active）。
- verify 端点只服务 mcp：配置 SERVICE_TOKENS 时调用方消费方名必须是 mcp。
  任何失败原因（不存在/撤销/过期/用户禁用/不在名单）一律 401 同一文案，
  不向调用方泄露令牌状态。

鉴权：与 auth.py 一致，router 级挂 read_access（service token）。
"""
from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Path, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.api._service_auth import ServiceIdentity, _tokens_map, read_access
from app.api.auth import session_user, sha256_hex
from app.config import settings
from app.db import get_pool

logger = logging.getLogger(__name__)

# 全文件统一挂 read_access（配置 SERVICE_TOKENS 后强制 X-Service-Token）
router = APIRouter(dependencies=[Depends(read_access)])

PAT_PREFIX = "tdk_pat_"
# 展示用前缀长度：tdk_pat_ + 4 位随机串（如 tdk_pat_ab12）
PAT_DISPLAY_PREFIX_LEN = 12
# scope 取值（顺序即规范顺序，入库/返回按此排序）
PAT_SCOPES: tuple[str, ...] = ("strategy:read", "strategy:write", "backtest")
# 每人有效（未撤销且未过期）令牌上限
PAT_MAX_ACTIVE_PER_USER = 5
# last_used_at 节流：距上次记录不足该秒数不再 UPDATE
_LAST_USED_THROTTLE_SECONDS = 60
# 只有该消费方可调 verify（SERVICE_TOKENS 配置时生效）
_VERIFY_CONSUMER = "mcp"
# verify 失败统一文案（不区分原因，防探测令牌状态）
_VERIFY_FAILED_DETAIL = "令牌无效或已过期"
# 列表返回上限（撤销/过期记录会累积，兜底防无界）
_LIST_LIMIT = 100
# BIGSERIAL 上界：路径参数越界直接 422，不让 asyncpg 编码溢出成 500
_BIGINT_MAX = 2**63 - 1
# 真实令牌 51 字符；超过该长度直接按无效 401，不进哈希与查库
_PAT_MAX_LEN = 256
# verify 请求体硬上限：超过才 422（纯防御超大输入；nginx 默认单请求头 8KB，
# mcp 透传的 Bearer 不会更长）
_VERIFY_BODY_MAX_LEN = 8192


# ---- 请求模型 ----


class CreateTokenRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=64)
    scopes: list[str] = Field(min_length=1)
    expires_days: int = Field(default=90, ge=1, le=365)

    @field_validator("scopes")
    @classmethod
    def _check_scopes(cls, value: list[str]) -> list[str]:
        unknown = [s for s in value if s not in PAT_SCOPES]
        if unknown:
            raise ValueError(f"未知 scope：{', '.join(unknown)}")
        # 去重并按规范顺序排列
        return [s for s in PAT_SCOPES if s in value]


class VerifyTokenRequest(BaseModel):
    # 只做请求体硬上限（防超大输入）；空串 / 超长但未达上限的输入在端点内
    # 按「令牌无效」401 处理，与契约「无效一律 401」对齐（mcp 透传客户端
    # 任意 Bearer，不应因输入形状不同拿到 422 而误判为上游故障）。
    token: str = Field(max_length=_VERIFY_BODY_MAX_LEN)


# ---- 内部工具 ----


def _pat_allowed(user_id: int) -> bool:
    """PAT_ALLOWED_USER_IDS 未配置（None）= 所有登录用户可用；配置后仅名单内
    用户（配置了但全部非法时为空集合 = 全部拒绝，见 config._parse_user_ids）。"""
    allowed = settings.PAT_ALLOWED_USER_IDS
    return allowed is None or user_id in allowed


def _token_status(row, now: datetime) -> str:
    if row["revoked_at"] is not None:
        return "revoked"
    if row["expires_at"] <= now:
        return "expired"
    return "active"


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _token_payload(row, now: datetime) -> dict:
    """列表项：绝不包含 token_hash。"""
    return {
        "id": row["id"],
        "name": row["name"],
        "token_prefix": row["token_prefix"],
        "scopes": list(row["scopes"]),
        "created_at": _iso(row["created_at"]),
        "expires_at": _iso(row["expires_at"]),
        "last_used_at": _iso(row["last_used_at"]),
        "revoked_at": _iso(row["revoked_at"]),
        "status": _token_status(row, now),
    }


def _verify_failed() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=_VERIFY_FAILED_DETAIL,
    )


# ---- 管理端点（session 鉴权）----


@router.post("/api/auth/tokens", status_code=status.HTTP_201_CREATED)
async def create_token(body: CreateTokenRequest, user=Depends(session_user)):
    """签发 PAT。名单外用户 403；有效令牌已达上限 409；明文仅本次返回。"""
    user_id = user["id"]
    if not _pat_allowed(user_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="当前账号未开通 API 令牌",
        )

    token = PAT_PREFIX + secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(days=body.expires_days)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            # 锁住用户行串行化同一用户的并发签发，防并发请求绕过数量上限
            await conn.execute(
                "SELECT id FROM auth.users WHERE id = $1 FOR UPDATE", user_id
            )
            active_count = await conn.fetchval(
                """
                SELECT count(*) FROM auth.api_tokens
                WHERE user_id = $1 AND revoked_at IS NULL AND expires_at > now()
                """,
                user_id,
            )
            if (active_count or 0) >= PAT_MAX_ACTIVE_PER_USER:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        f"有效令牌已达上限（{PAT_MAX_ACTIVE_PER_USER} 个），"
                        "请先撤销不用的令牌"
                    ),
                )
            row = await conn.fetchrow(
                """
                INSERT INTO auth.api_tokens
                    (user_id, name, token_prefix, token_hash, scopes, expires_at)
                VALUES ($1, $2, $3, $4, $5, $6)
                RETURNING id, name, token_prefix, scopes, created_at, expires_at
                """,
                user_id,
                body.name,
                token[:PAT_DISPLAY_PREFIX_LEN],
                sha256_hex(token),
                body.scopes,
                expires_at,
            )
    logger.info("PAT 签发 user_id=%s token_id=%s", user_id, row["id"])
    return {
        "id": row["id"],
        "name": row["name"],
        "token": token,
        "token_prefix": row["token_prefix"],
        "scopes": list(row["scopes"]),
        "created_at": _iso(row["created_at"]),
        "expires_at": _iso(row["expires_at"]),
    }


@router.get("/api/auth/tokens")
async def list_tokens(user=Depends(session_user)):
    """本人令牌列表，含已撤销/已过期记录，绝不返回哈希。

    排序：有效令牌在前，组内新的在前——保证截断到 _LIST_LIMIT 时有效令牌
    （≤5 个）必在列表内、可在页面撤销，不会被大量新近撤销的记录挤出去。
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, name, token_prefix, scopes, created_at, expires_at,
                   last_used_at, revoked_at
            FROM auth.api_tokens
            WHERE user_id = $1
            ORDER BY (revoked_at IS NULL AND expires_at > now()) DESC,
                     created_at DESC, id DESC
            LIMIT $2
            """,
            user["id"],
            _LIST_LIMIT,
        )
    now = datetime.now(timezone.utc)
    return [_token_payload(row, now) for row in rows]


@router.delete("/api/auth/tokens/{token_id}")
async def revoke_token(
    token_id: int = Path(ge=1, le=_BIGINT_MAX), user=Depends(session_user)
):
    """撤销本人令牌（置 revoked_at，重复撤销保留首次时间）。
    他人令牌与不存在同为 404，不泄露存在性。"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE auth.api_tokens
            SET revoked_at = COALESCE(revoked_at, now())
            WHERE id = $1 AND user_id = $2
            RETURNING id
            """,
            token_id,
            user["id"],
        )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="令牌不存在",
        )
    logger.info("PAT 撤销 user_id=%s token_id=%s", user["id"], token_id)
    return {"revoked": True, "id": row["id"]}


# ---- mcp 校验端点（服务令牌鉴权）----


@router.post("/api/auth/tokens/verify")
async def verify_token(
    body: VerifyTokenRequest,
    identity: ServiceIdentity = Depends(read_access),
):
    """mcp 校验 PAT：返回令牌代表的用户与 scope。

    调用方：SERVICE_TOKENS 配置时消费方必须是 mcp（否则 403）；未配置（dev）放行。
    令牌不存在/已撤销/已过期/用户非 active/用户不在 PAT_ALLOWED_USER_IDS
    一律 401 同一文案。last_used_at 节流到每分钟一次，更新失败只记日志。
    """
    # 鉴权已启用（env 配了令牌，或调用方经任一通道认证）时只认 mcp；
    # 未配置（dev）时匿名放行（自报 X-Service-Name 不作数）。
    auth_enabled = bool(_tokens_map()) or identity.authenticated
    if auth_enabled and not (
        identity.authenticated and identity.name == _VERIFY_CONSUMER
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="仅 mcp 服务可校验个人访问令牌",
        )
    token = body.token.strip()
    if not token.startswith(PAT_PREFIX) or len(token) > _PAT_MAX_LEN:
        raise _verify_failed()

    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT t.id, t.user_id, t.scopes, t.expires_at, t.last_used_at,
                   t.revoked_at, u.status AS user_status
            FROM auth.api_tokens t
            JOIN auth.users u ON u.id = t.user_id
            WHERE t.token_hash = $1
            """,
            sha256_hex(token),
        )
        now = datetime.now(timezone.utc)
        if (
            row is None
            or row["revoked_at"] is not None
            or row["expires_at"] <= now
            or row["user_status"] != "active"
            or not _pat_allowed(row["user_id"])
        ):
            raise _verify_failed()

        last_used = row["last_used_at"]
        threshold = now - timedelta(seconds=_LAST_USED_THROTTLE_SECONDS)
        if last_used is None or last_used < threshold:
            try:
                # WHERE 再判一次节流条件：并发 verify 时只有一个真正写入
                await conn.execute(
                    """
                    UPDATE auth.api_tokens SET last_used_at = now()
                    WHERE id = $1 AND (last_used_at IS NULL OR last_used_at < $2)
                    """,
                    row["id"],
                    threshold,
                )
            except Exception:
                logger.warning(
                    "PAT last_used_at 更新失败（丢弃）token_id=%s",
                    row["id"],
                    exc_info=True,
                )

    return {
        "user_id": f"u{row['user_id']}",
        "scopes": list(row["scopes"]),
        "expires_at": row["expires_at"].isoformat(),
        "token_id": row["id"],
    }
