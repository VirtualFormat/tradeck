"""quant 入站鉴权：服务令牌（X-Service-Token）门槛 + 用户身份收口。

设计（docs/MCP.md「P0 quant 加固」）：
- quant 的消费方只有 web BFF 与 mcp 服务，二者都持服务令牌；X-User-Id 只有在
  服务令牌校验通过后才可信（否则任何能连到 8083 的人都能冒充任意用户）。
- INBOUND_SERVICE_TOKENS 为空时整体放行（dev / 旧部署兼容，行为与改造前一致）；
  非空时除 /health 探活外一律要求有效令牌，缺失/错误 401；非空但格式非法时
  fail-closed（非探活请求一律 503），不静默降级为放行。
- 纯 ASGI 中间件（不用 BaseHTTPMiddleware：后者包装响应体，对流式响应与
  后台任务有已知坑）；lifespan 事件直接透传。
- 令牌比较用 hmac.compare_digest 逐个比对（常量时间，避免按前缀试探）。
"""
from __future__ import annotations

import hmac
import json
import logging

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.config import settings

logger = logging.getLogger(__name__)

# 不鉴权的路径：仅探活（deploy-cn.sh / compose healthcheck 用）
_PUBLIC_PATHS = frozenset({"/health"})


class InboundConfigError(ValueError):
    """INBOUND_SERVICE_TOKENS 非空但不合法（fail-closed：拒绝一切非探活请求）。"""


def _parse_tokens(raw: str) -> dict[str, str]:
    """解析 {"<token>": "<consumer>"}；非空但格式非法抛 InboundConfigError。"""
    try:
        data = json.loads(raw)
    except (ValueError, TypeError) as e:
        raise InboundConfigError(f"不是合法 JSON：{e}") from e
    if not isinstance(data, dict):
        raise InboundConfigError("必须是 JSON 对象 {\"<token>\": \"<consumer>\"}")
    tokens = {str(k).strip(): str(v).strip() for k, v in data.items()}
    tokens = {k: v for k, v in tokens.items() if k and v}
    if not tokens:
        raise InboundConfigError("未包含任何有效的 token → consumer 映射")
    return tokens


def inbound_tokens() -> dict[str, str]:
    """解析 INBOUND_SERVICE_TOKENS；空串返回 {}（未启用）。

    非空但非法时抛 InboundConfigError——与 PAT_ALLOWED_USER_IDS 同口径 fail-closed：
    运维以为已收口而实际静默放行，比直接报错危险得多（X-User-Id 会被无条件采信）。
    """
    raw = settings.INBOUND_SERVICE_TOKENS.strip()
    if not raw:
        return {}
    return _parse_tokens(raw)


def inbound_auth_enabled() -> bool:
    """入站鉴权是否启用：配置非空即视为启用（非法配置也按启用处理，fail-closed）。"""
    return bool(settings.INBOUND_SERVICE_TOKENS.strip())


def log_inbound_status() -> None:
    """启动时打一行入站鉴权状态（便于部署后核对）；配置非法记 error。"""
    try:
        tokens = inbound_tokens()
    except InboundConfigError as e:
        logger.error("INBOUND_SERVICE_TOKENS 配置非法，quant 将拒绝全部非探活请求：%s", e)
        return
    if tokens:
        logger.info("quant 入站鉴权已启用，consumer：%s", sorted(set(tokens.values())))
    else:
        logger.warning("quant 入站鉴权未启用（INBOUND_SERVICE_TOKENS 为空），X-User-Id 无条件采信")


def match_consumer(token: str, tokens: dict[str, str]) -> str | None:
    """常量时间比对令牌，命中返回消费方名，否则 None。"""
    if not token:
        return None
    hit = None
    for known, consumer in tokens.items():
        # 不提前 return：每个候选都比一遍，耗时与命中位置无关
        if hmac.compare_digest(token.encode(), known.encode()):
            hit = consumer
    return hit


def _header(scope: Scope, name: bytes) -> str:
    for key, value in scope.get("headers") or []:
        if key.lower() == name:
            return value.decode("latin-1").strip()
    return ""


class InboundAuthMiddleware:
    """入站服务令牌门槛：启用后无有效 X-Service-Token 的请求直接 401。"""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan" or scope.get("path") in _PUBLIC_PATHS:
            await self.app(scope, receive, send)
            return
        try:
            tokens = inbound_tokens()
        except InboundConfigError:
            response = JSONResponse(
                {"detail": "quant 入站鉴权配置非法，拒绝服务（检查 INBOUND_SERVICE_TOKENS）"},
                status_code=503,
            )
            await response(scope, receive, send)
            return
        if not tokens:
            await self.app(scope, receive, send)
            return
        consumer = match_consumer(_header(scope, b"x-service-token"), tokens)
        if consumer is None:
            response = JSONResponse(
                {"detail": "缺少有效的 X-Service-Token（quant 仅接受 web / mcp 服务调用）"},
                status_code=401,
            )
            await response(scope, receive, send)
            return
        scope.setdefault("state", {})["service_consumer"] = consumer
        await self.app(scope, receive, send)
