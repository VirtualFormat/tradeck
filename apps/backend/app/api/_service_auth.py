"""消费方鉴权（service token，data-api 作为唯一数据出口的扩展位）。

设计意图：data-api 成为所有消费方（web-bff / 量化 / 回测）的唯一入口后，
需要能区分消费方身份——用于按消费方限流、审计与未来的访问控制收紧。

现阶段策略（内网公开行情，渐进收紧）：
- 公开读接口（quotes/historical/...）：token 可空放行，仅识别 + 记录消费方。
- 量化批量接口（/api/bars 等重操作）：已配置 SERVICE_TOKENS 时强制有效 token。

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
    未配置（内网默认）放行——与 CORS allow_origins=* 的现阶段公开策略一致。
    """
    if _tokens_map() and not identity.authenticated:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="缺少有效的 X-Service-Token（量化批量接口需要消费方鉴权）",
        )
    return identity
