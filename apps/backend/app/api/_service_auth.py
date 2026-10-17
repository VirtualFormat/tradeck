"""消费方鉴权（service token，data-api 作为唯一数据出口的扩展位）。

设计意图：data-api 成为所有消费方（web-bff / 量化 / 回测）的唯一入口后，
需要能区分消费方身份——用于按消费方限流、配额管控与审计。

token 双读合并（方案 docs/ADMIN-AUTH.md §3，阶段一/二）：
- env SERVICE_TOKENS（明文 JSON {"<token>": "<consumer_name>"}）：emergency
  fallback 通道，管理员误锁所有人时仍可进。env 命中的身份不做配额、不计数
  （无 token_id），随消费方迁往 DB 后逐步清空。
- DB service_tokens 表（sha256(token) 查 token_hash，仅 status='active' 且
  未过期生效）：管理员页面分配的主通道。进程内缓存 TTL 60s；DB 查询失败
  fail-open——沿用上次缓存，无缓存则视为鉴权未启用=放行，记 error 日志
  （与全仓优雅降级哲学一致）。

配额（阶段二）：DB token 校验通过后，若 quota_limit 非 NULL，检查当前窗口
（day=UTC 零点对齐 / hour=整点对齐）service_token_usage.request_count，超限
返回 429 + Retry-After。配额检查本身 DB 失败同样 fail-open。

用量计数（方案 §4 受控写例外）：「data-api 不写库」铁律指业务数据；身份
校验通过且为 DB token 时，fire-and-forget 异步 UPSERT service_token_usage，
失败丢弃不重试——计数丢一点无妨，请求不能挂。

三个依赖（签名与对外语义保持不变）：
- read_access（全部读接口，含 /api/system/*）：任一通道配置了有效 token
  时强制鉴权；均未配置（内网默认）全部放行。/health 探活不鉴权。
- quant_access（/api/bars、/api/bars/minute）：与 read_access 同门槛，
  语义标记「批量/重操作」，DB token 的 quota_limit 即按消费方差异化限流的
  真实落点。
- service_identity：只识别不强制，供审计。

请求头：
- X-Service-Token：消费方令牌。
- X-Service-Name：消费方自报名（web-bff / quant / backtest ...），便于审计。
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import Depends, Header, HTTPException, status

from app.config import settings
from app.db import get_pool

logger = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 60.0
# 进程内缓存：token_hash -> _DbTokenRecord。None = 尚未查过（首个请求触发查询）。
_db_tokens_cache: dict[str, _DbTokenRecord] | None = None
_db_tokens_cached_at: float = 0.0


@dataclass(frozen=True)
class ServiceIdentity:
    """一次请求的消费方身份。"""

    name: str  # token 解析出的消费方名，或自报的 X-Service-Name，或 anonymous
    authenticated: bool  # 是否持有效 token
    db_record: _DbTokenRecord | None = None  # DB token 命中时的配额/计数记录


@dataclass(frozen=True)
class _DbTokenRecord:
    """service_tokens 表中一条可用（active 且未过期）令牌的缓存视图。"""

    id: int
    consumer: str
    quota_limit: int | None
    quota_window: str  # day / hour


def _tokens_map() -> dict[str, str]:
    """解析 SERVICE_TOKENS JSON（emergency fallback）；非法返回空 dict。"""
    raw = settings.SERVICE_TOKENS.strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except (ValueError, TypeError):
        logger.warning("SERVICE_TOKENS 配置非法（应为 JSON 对象），鉴权按未启用处理")
        return {}


async def _load_db_tokens() -> dict[str, _DbTokenRecord] | None:
    """从 DB 加载全部可用令牌（sha256 -> 记录）；DB 失败返回 None。"""
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, token_hash, consumer, quota_limit, quota_window
                FROM service_tokens
                WHERE status = 'active'
                  AND (expires_at IS NULL OR expires_at > NOW())
                """
            )
    except Exception:
        logger.error("service_tokens 加载失败（鉴权按缓存/未启用降级）", exc_info=True)
        return None
    return {
        row["token_hash"]: _DbTokenRecord(
            id=row["id"],
            consumer=row["consumer"],
            quota_limit=row["quota_limit"],
            quota_window=row["quota_window"] or "day",
        )
        for row in rows
    }


async def _db_tokens() -> dict[str, _DbTokenRecord] | None:
    """带 TTL 的令牌缓存。返回 None 表示「缓存为空且 DB 也不可达」。"""
    global _db_tokens_cache, _db_tokens_cached_at
    now = time.monotonic()
    if _db_tokens_cache is not None and now - _db_tokens_cached_at < _CACHE_TTL_SECONDS:
        return _db_tokens_cache
    fresh = await _load_db_tokens()
    if fresh is not None:
        _db_tokens_cache = fresh
        _db_tokens_cached_at = now
        return fresh
    if _db_tokens_cache is None:
        logger.error(
            "service_tokens 首次加载即失败且无缓存，鉴权按未启用处理（fail-open）"
        )
    # DB 失败：沿用上次缓存（可能为 None）
    return _db_tokens_cache


def _window_start(window: str, now: datetime) -> datetime:
    """当前配额窗口起点（UTC 对齐）。"""
    if window == "hour":
        return now.replace(minute=0, second=0, microsecond=0)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _retry_after_seconds(window: str, now: datetime) -> int:
    """到当前窗口结束的秒数（作为 Retry-After，至少 1s）。"""
    if window == "hour":
        return max(1, 3600 - (now.minute * 60 + now.second))
    return max(1, 86400 - (now.hour * 3600 + now.minute * 60 + now.second))


async def _enforce_quota(record: _DbTokenRecord, consumer: str) -> None:
    """配额超限抛 429；quota_limit 为 NULL 或 DB 失败（fail-open）直接放行。"""
    if record.quota_limit is None:
        return
    window_start = _window_start(record.quota_window, datetime.now(timezone.utc))
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            count = await conn.fetchval(
                """
                SELECT request_count FROM service_token_usage
                WHERE token_id = $1 AND window_start = $2
                """,
                record.id,
                window_start,
            )
    except Exception:
        logger.error(
            "配额检查失败（fail-open 放行）token_id=%s", record.id, exc_info=True
        )
        return
    if (count or 0) >= record.quota_limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"消费方 {consumer} 的 {record.quota_window} 配额已用尽"
                f"（{record.quota_limit} 次/窗口），请下个窗口重试"
            ),
            headers={
                "Retry-After": str(
                    _retry_after_seconds(record.quota_window, datetime.now(timezone.utc))
                )
            },
        )


async def _increment_usage(token_id: int, window_start: datetime) -> None:
    """UPSERT 累加用量（方案 §4 受控写例外）；失败丢弃，绝不影响请求。"""
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO service_token_usage (token_id, window_start, request_count)
                VALUES ($1, $2, 1)
                ON CONFLICT (token_id, window_start)
                DO UPDATE SET request_count = service_token_usage.request_count + 1
                """,
                token_id,
                window_start,
            )
    except Exception:
        logger.warning(
            "用量计数失败（丢弃）token_id=%s", token_id, exc_info=True
        )


async def service_identity(
    x_service_token: str | None = Header(None),
    x_service_name: str | None = Header(None),
) -> ServiceIdentity:
    """识别消费方身份（不强制）。公开读接口可用此依赖做审计记录。"""
    tokens = _tokens_map()
    token = (x_service_token or "").strip()
    if token and token in tokens:
        # env emergency fallback 通道：不做配额、不计数（无 token_id）。
        return ServiceIdentity(name=tokens[token], authenticated=True)
    if token:
        db_tokens = await _db_tokens()
        if db_tokens:
            record = db_tokens.get(hashlib.sha256(token.encode()).hexdigest())
            if record is not None:
                asyncio.create_task(
                    _increment_usage(
                        record.id,
                        _window_start(record.quota_window, datetime.now(timezone.utc)),
                    )
                )
                return ServiceIdentity(
                    name=record.consumer, authenticated=True, db_record=record
                )
            return ServiceIdentity(name="unknown", authenticated=False)
        # db_tokens 为 None：缓存为空且 DB 不可达，fail-open 按匿名放行。
    # 无 token 或 token 未识别：回落自报名（便于审计），未鉴权。
    fallback = (x_service_name or "anonymous").strip() or "anonymous"
    return ServiceIdentity(name=fallback, authenticated=False)


async def _enforce_access(
    identity: ServiceIdentity, scope: str
) -> ServiceIdentity:
    """read/quant 共用的门槛与配额逻辑。"""
    auth_enabled = bool(_tokens_map())
    db_tokens = await _db_tokens()
    if db_tokens is not None:
        auth_enabled = auth_enabled or bool(db_tokens)
    # db_tokens 为 None（缓存空 + DB 挂）按鉴权未启用处理（fail-open）。
    if auth_enabled and not identity.authenticated:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"缺少有效的 X-Service-Token（{scope}需要消费方鉴权）",
        )
    # env emergency token 与匿名身份无配额（db_record 仅 DB token 命中时携带）。
    if identity.db_record is not None:
        await _enforce_quota(identity.db_record, identity.name)
    return identity


async def quant_access(
    identity: ServiceIdentity = Depends(service_identity),
) -> ServiceIdentity:
    """量化批量接口的访问门槛：任一鉴权通道配置了有效 token 时强制；
    均未配置（内网默认）放行。

    与 read_access 同构，语义上标记「批量/重操作」接口；挂在 /api/bars、
    /api/bars/minute 上，DB token 的 quota_limit 是按消费方差异化限流的落点。
    """
    return await _enforce_access(identity, "量化批量接口")


async def read_access(
    identity: ServiceIdentity = Depends(service_identity),
) -> ServiceIdentity:
    """读接口的访问门槛：任一鉴权通道配置了有效 token 时强制；
    均未配置（内网默认）放行，与未启用鉴权的历史行为一致。

    挂在全部读路由（含 /api/system/* 内部运维端点——不对外暴露 ≠ 不鉴权）
    的 router 级 dependencies 上；/health 探活不鉴权。
    """
    return await _enforce_access(identity, "读接口")
