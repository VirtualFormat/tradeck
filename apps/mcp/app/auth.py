"""PAT 校验：实现 SDK 的 TokenVerifier 协议，委托 api 服务 /api/auth/tokens/verify。

- 非 `tdk_pat_` 前缀直接拒（不打 api，挡掉随手乱填/误用 session token）。
- 按 sha256(token) 缓存校验结果：成功 30 秒（撤销最迟 30 秒生效，docs/MCP.md）、
  失败 5 秒（挡住同一坏令牌短时间内反复打 api）。缓存只存哈希与校验结果，不存明文。
- 用户身份只来自 verify 结果：user_id（u<id>）同时放进 AccessToken.client_id 与 subject，
  工具内经 get_access_token() 取用；工具参数里绝不接受用户字段。
- resource 设为本服务 resource url：AuthSettings(validate_token_resource=True) 时
  SDK 的 BearerAuthBackend 会比对 AccessToken.resource，PAT 只为本服务签发，故恒等于它。
- 任何非 200 / 网络错误 / 响应结构不符都视为校验失败（返回 None，SDK 回 401），只记日志
  （日志只打哈希前缀，绝不打明文令牌）。
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx2
from mcp.server.auth.provider import AccessToken

from app.config import Settings

logger = logging.getLogger(__name__)

PAT_PREFIX = "tdk_pat_"
# 缓存时长（秒）：成功 30s（撤销生效延迟上限）、失败 5s
SUCCESS_TTL_SECONDS = 30.0
FAILURE_TTL_SECONDS = 5.0
# 缓存条目上限：防随机伪造令牌刷爆内存（超限先清过期，仍超限整体清空）
_CACHE_MAX_ENTRIES = 4096
# user_id 口径与 quant current_user_id 的校验一致（会作为 X-User-Id 头透传）
_USER_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
# 令牌长度上限：tdk_pat_ + 32 字节 urlsafe（43 字符），留足余量又不让超长串打到 api
_MAX_TOKEN_LEN = 256


def token_hash(token: str) -> str:
    """令牌 sha256 hex（缓存键 / 配额键 / 日志标识，均不落明文）。"""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class _VerifiedToken:
    """verify 成功结果（缓存值，不含明文令牌）。"""

    user_id: str
    scopes: tuple[str, ...]
    expires_at: int | None
    token_id: str | None


def _parse_expires_at(value: object) -> int | None:
    """ISO8601 → epoch 秒；无时区按 UTC。非法值抛 ValueError（按校验失败处理）。"""
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"expires_at 非法：{value!r}")
    dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def _parse_verify_body(body: object) -> _VerifiedToken:
    """校验 api 返回结构：{user_id, scopes, expires_at, token_id}；不符抛 ValueError。"""
    if not isinstance(body, dict):
        raise ValueError("响应不是 JSON 对象")
    user_id = body.get("user_id")
    if not isinstance(user_id, str) or not _USER_ID_RE.fullmatch(user_id):
        raise ValueError(f"user_id 非法：{user_id!r}")
    scopes = body.get("scopes")
    if not isinstance(scopes, list) or not all(isinstance(s, str) for s in scopes):
        raise ValueError("scopes 非字符串数组")
    token_id = body.get("token_id")
    return _VerifiedToken(
        user_id=user_id,
        scopes=tuple(scopes),
        expires_at=_parse_expires_at(body.get("expires_at")),
        token_id=None if token_id is None else str(token_id),
    )


class PatVerifier:
    """个人访问令牌校验器（SDK TokenVerifier 协议：async verify_token(token) -> AccessToken | None）。"""

    def __init__(
        self,
        settings: Settings,
        client: httpx2.AsyncClient,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._settings = settings
        self._client = client
        self._clock = clock
        # token_hash -> (缓存到期时刻（clock 口径）, 校验结果；None = 失败)
        self._cache: dict[str, tuple[float, _VerifiedToken | None]] = {}

    async def verify_token(self, token: str) -> AccessToken | None:
        token = (token or "").strip()
        if not token.startswith(PAT_PREFIX) or len(token) > _MAX_TOKEN_LEN:
            return None
        key = token_hash(token)
        now = self._clock()
        hit = self._cache.get(key)
        if hit is not None and hit[0] > now:
            verified = hit[1]
        else:
            verified = await self._remote_verify(token, key)
            ttl = SUCCESS_TTL_SECONDS if verified is not None else FAILURE_TTL_SECONDS
            self._store(key, now + ttl, verified)
        if verified is None:
            return None
        return AccessToken(
            token=token,
            client_id=verified.user_id,
            subject=verified.user_id,
            scopes=list(verified.scopes),
            expires_at=verified.expires_at,
            resource=self._settings.resource_url,
            claims={"token_id": verified.token_id} if verified.token_id else None,
        )

    async def _remote_verify(self, token: str, key: str) -> _VerifiedToken | None:
        """调 api verify；任何失败返回 None 并记日志（只打哈希前缀）。"""
        try:
            resp = await self._client.post(
                "/api/auth/tokens/verify",
                json={"token": token},
                headers={
                    "X-Service-Token": self._settings.service_token,
                    "X-Service-Name": "mcp",
                },
            )
        except (
            Exception
        ) as e:  # noqa: BLE001 - 鉴权路径一律 fail-closed（返回 None → 401），绝不 500
            logger.warning(
                "PAT 校验请求失败（token=%s…）：%s", key[:8], type(e).__name__
            )
            return None
        if resp.status_code != 200:
            # 401 = 无效/撤销/过期/用户禁用（常态拒绝）；403 多为 mcp 服务令牌配置错误
            level = logging.INFO if resp.status_code == 401 else logging.WARNING
            logger.log(
                level, "PAT 校验拒绝（token=%s…）：HTTP %d", key[:8], resp.status_code
            )
            return None
        try:
            return _parse_verify_body(resp.json())
        except ValueError as e:
            logger.warning("PAT 校验响应结构非法（token=%s…）：%s", key[:8], e)
            return None

    def _store(self, key: str, expires: float, value: _VerifiedToken | None) -> None:
        if len(self._cache) >= _CACHE_MAX_ENTRIES:
            now = self._clock()
            self._cache = {k: v for k, v in self._cache.items() if v[0] > now}
            if len(self._cache) >= _CACHE_MAX_ENTRIES:
                self._cache.clear()
        self._cache[key] = (expires, value)
