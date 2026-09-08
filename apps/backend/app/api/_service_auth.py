"""消费方鉴权（service token，data-api 作为唯一数据出口的扩展位）。

设计意图：data-api 成为所有消费方（web-bff / 量化 / 回测）的唯一入口后，
需要能区分消费方身份——用于按消费方限流、审计与未来的访问控制收紧。

现阶段策略（分两级，均复用同一份 SERVICE_TOKENS）：
- read_access（全部读接口，含内部运维端点 /api/system/*）：已配置
  SERVICE_TOKENS 时强制有效 token；未配置（内网默认）全部放行，与历史
  行为兼容。/health 探活不鉴权。
- quant_access（量化批量重操作接口 /api/bars、/api/bars/minute）：强制
  级别与 read_access 相同，单独保留作语义标记（批量/重操作），未来需要
  更严（如独立令牌表、更紧限流）时只动这一个依赖。

配置（config.py）：
- SERVICE_TOKENS：JSON 对象串 {"<token>": "<consumer_name>"}；
  空 = 未启用鉴权（内网默认，全部放行，仍可经 X-Service-Name 自报审计）。

请求头：
- X-Service-Token：消费方令牌。
- X-Service-Name：消费方自报名（web-bff / quant / backtest ...），便于审计。
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, status

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ServiceIdentity:
    """一次请求的消费方身份。"""

    name: str  # token 解析出的消费方名，或自报的 X-Service-Name，或 anonymous
    authenticated: bool  # 是否持有效 token


def _tokens_map() -> dict[str, str]:
    """解析 SERVICE_TOKENS JSON；未配置/解析失败返回空 dict（鉴权未启用）。"""
    raw = settings.SERVICE_TOKENS.strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except (ValueError, TypeError):
        logger.warning("SERVICE_TOKENS 配置非法（应为 JSON 对象），鉴权按未启用处理")
        return {}


async def service_identity(
    x_service_token: str | None = Header(None),
    x_service_name: str | None = Header(None),
) -> ServiceIdentity:
    """识别消费方身份（不强制）。公开读接口可用此依赖做审计记录。"""
    tokens = _tokens_map()
    token = (x_service_token or "").strip()
    if token and token in tokens:
        return ServiceIdentity(name=tokens[token], authenticated=True)
    # 无 token 或 token 未识别：回落自报名（便于审计），未鉴权。
    fallback = (x_service_name or "anonymous").strip() or "anonymous"
    return ServiceIdentity(name=fallback, authenticated=False)


async def quant_access(
    identity: ServiceIdentity = Depends(service_identity),
) -> ServiceIdentity:
    """量化批量接口的访问门槛：已配置 SERVICE_TOKENS 时强制有效 token；
    未配置（内网默认）放行。

    与 read_access 同构，语义上标记「批量/重操作」接口；挂在 /api/bars、
    /api/bars/minute 上，未来收紧只改这里。
    """
    if _tokens_map() and not identity.authenticated:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="缺少有效的 X-Service-Token（量化批量接口需要消费方鉴权）",
        )
    return identity


async def read_access(
    identity: ServiceIdentity = Depends(service_identity),
) -> ServiceIdentity:
    """读接口的访问门槛：已配置 SERVICE_TOKENS 时强制有效 token；
    未配置（内网默认）放行，与未启用鉴权的历史行为一致。

    挂在全部读路由（含 /api/system/* 内部运维端点——不对外暴露 ≠ 不鉴权）
    的 router 级 dependencies 上；/health 探活不鉴权。
    """
    if _tokens_map() and not identity.authenticated:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="缺少有效的 X-Service-Token（读接口需要消费方鉴权）",
        )
    return identity
