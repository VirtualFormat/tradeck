"""mcp 服务入口：外层 Starlette 挂 /health + SDK 生成的 MCP 子应用（/mcp 与 resource metadata）。

- MCP 端点 /mcp：无状态 + JSON 响应（stateless_http / json_response），不依赖长连接，过 CF 稳定。
- 鉴权：SDK 的 BearerAuthBackend + RequireAuthMiddleware；无/错 Bearer → 401，
  WWW-Authenticate 带 resource_metadata（/.well-known/oauth-protected-resource/mcp，不鉴权）。
- Host 白名单：由 MCP_PUBLIC_URL 推出（+ MCP_ALLOWED_HOSTS）；不配时带真实 Host 的请求一律 421。
- /health：外层直挂，不鉴权、不受 Host 白名单约束（deploy-cn.sh / compose 健康检查走回环）。
- lifespan：外层 app 不会自动进入被挂载子应用的 lifespan，必须在这里进入 session_manager.run()，
  否则首个 /mcp 请求即报「Task group is not initialized」。

单进程纪律：PAT 校验缓存与配额计数都在进程内存，uvicorn 必须 --workers 1（见 Dockerfile）。
"""

from __future__ import annotations

import contextlib
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable

import anyio
import httpx2
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from app.auth import PatVerifier
from app.config import Settings, load_settings
from app.quant_client import QUANT_TIMEOUT, QuantClient
from app.tools import build_server

logger = logging.getLogger(__name__)

# 调 api 校验 PAT：轻请求，超时收紧（失败即 401，客户端重试即可）
AUTH_TIMEOUT = httpx2.Timeout(10.0, connect=5.0)
# MCP 请求体上限：策略代码 ≤200KB（工具内校验），JSON 转义后留足余量；nginx 侧另有 1m 上限
MAX_REQUEST_BODY_BYTES = 1024 * 1024


async def health(_: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


def create_app(
    settings: Settings | None = None,
    *,
    auth_transport: httpx2.AsyncBaseTransport | None = None,
    quant_transport: httpx2.AsyncBaseTransport | None = None,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], Awaitable[None]] = anyio.sleep,
) -> Starlette:
    """组装 ASGI 应用。

    transport 可注入 MockTransport（测试模拟 api / quant）；clock / sleep 可注入假时钟
    （测试校验缓存过期、配额窗口与长轮询，不真等）。
    """
    settings = settings or load_settings()
    auth_http = httpx2.AsyncClient(
        base_url=settings.auth_api_url,
        timeout=AUTH_TIMEOUT,
        transport=auth_transport,
    )
    quant_http = httpx2.AsyncClient(
        base_url=settings.quant_api_url,
        timeout=QUANT_TIMEOUT,
        transport=quant_transport,
    )
    mcp = build_server(
        settings,
        PatVerifier(settings, auth_http, clock=clock),
        QuantClient(settings, quant_http),
        sleep=sleep,
        clock=clock,
    )
    mcp_app = mcp.streamable_http_app(
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
        max_request_body_size=MAX_REQUEST_BODY_BYTES,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=settings.allowed_hosts,
            allowed_origins=settings.allowed_origins,
        ),
    )

    @contextlib.asynccontextmanager
    async def lifespan(_: Starlette) -> AsyncIterator[None]:
        logger.info(
            "mcp 服务启动：resource=%s allowed_hosts=%s",
            settings.resource_url,
            settings.allowed_hosts,
        )
        async with mcp.session_manager.run():
            try:
                yield
            finally:
                await auth_http.aclose()
                await quant_http.aclose()

    return Starlette(
        routes=[
            Route("/health", health, methods=["GET"]),
            # 子应用自带 /mcp 与 /.well-known/oauth-protected-resource/mcp 两条路由
            Mount("/", app=mcp_app),
        ],
        lifespan=lifespan,
    )


logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
app = create_app()
