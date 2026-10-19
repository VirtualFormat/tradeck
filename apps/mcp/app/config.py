"""mcp 服务配置：全部从环境变量读取（纯 os.getenv，不额外引入 pydantic-settings）。

变量口径见 docs/MCP.md「环境变量」：
- MCP_SERVICE_TOKEN：同一把服务令牌同时用于调 api（tokens/verify，api 侧 SERVICE_TOKENS 映射 mcp）
  与 quant（入站鉴权，quant 侧 INBOUND_SERVICE_TOKENS 映射 mcp）。
- MCP_PUBLIC_URL：对外地址（如 https://tradeck.virtualformat.cn）；resource = MCP_PUBLIC_URL + "/mcp"，
  Host 白名单由其 host 推出（不配白名单时 SDK 对带真实 Host 的请求一律 421）。
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    """读整数环境变量；缺失/非法/小于下限时回落默认值并告警（配置错误不阻塞启动）。"""
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        logger.warning("%s=%r 非整数，使用默认值 %d", name, raw, default)
        return default
    if value < minimum:
        logger.warning(
            "%s=%d 小于下限 %d，使用默认值 %d", name, value, minimum, default
        )
        return default
    return value


@dataclass(frozen=True)
class Settings:
    """mcp 服务运行配置（测试可直接构造，不经环境变量）。"""

    service_token: str = ""
    auth_api_url: str = "http://api:8080"
    quant_api_url: str = "http://quant:8083"
    public_url: str = "http://localhost:8084"
    extra_allowed_hosts: tuple[str, ...] = field(default_factory=tuple)
    rate_per_minute: int = 60
    backtests_per_hour: int = 30
    max_code_bytes: int = 200_000

    @property
    def public_base(self) -> str:
        """去掉尾斜杠的对外基址。"""
        return self.public_url.rstrip("/")

    @property
    def resource_url(self) -> str:
        """RFC 8707 resource（受保护资源标识）= 对外基址 + /mcp。"""
        return self.public_base + "/mcp"

    @property
    def allowed_hosts(self) -> list[str]:
        """Host 头白名单：对外 host（含/不含端口两种写法）+ MCP_ALLOWED_HOSTS 追加项。

        nginx 以 `proxy_set_header Host $host` 透传，Host 不带端口；同时放行 `host:*`，
        便于经 SSH 隧道等带端口方式直连调试。
        """
        parts = urlsplit(self.public_base)
        hosts: list[str] = []
        if parts.hostname:
            hosts += [parts.hostname, f"{parts.hostname}:*"]
        if parts.netloc and parts.netloc not in hosts:
            hosts.append(parts.netloc)
        for h in self.extra_allowed_hosts:
            if h and h not in hosts:
                hosts.append(h)
        return hosts

    @property
    def allowed_origins(self) -> list[str]:
        """Origin 白名单（CLI/IDE 类 MCP 客户端通常不带 Origin，缺省即放行）。"""
        parts = urlsplit(self.public_base)
        return (
            [f"{parts.scheme}://{parts.netloc}"]
            if parts.scheme and parts.netloc
            else []
        )


def load_settings() -> Settings:
    """从进程环境构造 Settings。"""
    public_url = os.getenv("MCP_PUBLIC_URL", "").strip() or "http://localhost:8084"
    parts = urlsplit(public_url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        logger.warning(
            "MCP_PUBLIC_URL=%r 非法（应为 http(s)://host），回落 http://localhost:8084",
            public_url,
        )
        public_url = "http://localhost:8084"
    extra = tuple(
        h.strip() for h in os.getenv("MCP_ALLOWED_HOSTS", "").split(",") if h.strip()
    )
    settings = Settings(
        service_token=os.getenv("MCP_SERVICE_TOKEN", "").strip(),
        auth_api_url=(
            os.getenv("AUTH_API_URL", "").strip() or "http://api:8080"
        ).rstrip("/"),
        quant_api_url=(
            os.getenv("QUANT_API_URL", "").strip() or "http://quant:8083"
        ).rstrip("/"),
        public_url=public_url,
        extra_allowed_hosts=extra,
        rate_per_minute=_env_int("MCP_RATE_PER_MINUTE", 60),
        backtests_per_hour=_env_int("MCP_BACKTESTS_PER_HOUR", 30),
        max_code_bytes=_env_int("MCP_MAX_CODE_BYTES", 200_000),
    )
    if not settings.service_token:
        # 不阻塞启动（dev 可只起 /health）；但 api 的 verify 要求 mcp 服务令牌，届时所有 PAT 都会被拒
        logger.warning(
            "MCP_SERVICE_TOKEN 未配置：api 令牌校验与 quant 入站鉴权都会失败"
        )
    return settings
