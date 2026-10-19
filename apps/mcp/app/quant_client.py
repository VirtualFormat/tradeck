"""quant 服务客户端：统一注入服务令牌与用户身份，把 HTTP 结果翻译成工具语义。

- 每次请求带 X-Service-Token=MCP_SERVICE_TOKEN、X-Service-Name=mcp、X-User-Id=<令牌所属用户>；
  user_id 只来自 PAT 校验结果（调用方传入），绝不来自工具参数。
- 超时（与上下游时限对齐）：
  - 默认 connect 5s / read 70s：quant 的 validate/save 含沙箱试加载（子进程上限 60s，超时后杀进程组
    并等待回收），run 含预拉暖缓存；必须明显长于 60s，否则慢策略的「试加载超时」业务结果会被本端
    超时盖成「服务不可用」；又须让「PAT 校验（read 10s）+ 本请求」不超过 nginx proxy_read_timeout 90s
    （CF 免费版 100s），保证工具错误先于网关 504 返回。
  - 任务轮询/取消 read 20s：长轮询 wait_seconds ≤50，整次工具调用 ≤ 10 + 50 + 20 < 90s。
  - 超时单独抛 QuantTimeoutError（服务端可能仍在处理，文案与「不可用」区分，避免 agent 盲目重复提交）。
- 4xx 带 detail → QuantClientError（status + detail，detail 截断 2KB，便于 agent 自修又不成为外带通道）；
  401/403 是 mcp 服务令牌配置问题（非调用方过错），与 5xx / 网络错误 / 响应非 JSON 一样
  → QuantUnavailableError（通用「quant 服务暂不可用」，细节只进日志）。
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx2

from app.config import Settings

logger = logging.getLogger(__name__)

# 错误回显上限（与 quant sandbox.truncate_error 同口径 2KB）
DETAIL_LIMIT = 2048
# 默认请求超时：> quant 沙箱试加载上限 60s，叠加 PAT 校验仍 ≤ nginx 90s（见模块 docstring）
QUANT_TIMEOUT = httpx2.Timeout(70.0, connect=5.0)
# 任务轮询/取消：注册表查询是轻操作，收紧到 20s，保证长轮询整次调用 < 90s
TASK_TIMEOUT = httpx2.Timeout(20.0, connect=5.0)


def truncate(text: str, limit: int = DETAIL_LIMIT) -> str:
    """按字符截断并注明原长度。"""
    if len(text) <= limit:
        return text
    return text[:limit] + f"…（已截断，共 {len(text)} 字符）"


def _detail_text(detail: Any) -> str:
    """FastAPI detail 可能是字符串或 422 校验错误列表，统一成可读文本（缺失返回空串）。"""
    if detail is None:
        return ""
    if isinstance(detail, str):
        return detail
    if isinstance(detail, list):
        parts = []
        for item in detail:
            if isinstance(item, dict):
                loc = ".".join(str(p) for p in item.get("loc", []) if p != "body")
                msg = str(item.get("msg", ""))
                parts.append(f"{loc}: {msg}" if loc else msg)
            else:
                parts.append(str(item))
        return "；".join(p for p in parts if p)
    return json.dumps(detail, ensure_ascii=False, default=str)


class QuantClientError(Exception):
    """quant 返回 4xx（调用方可据 status 做 404 等特殊文案）。"""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


class QuantUnavailableError(Exception):
    """quant 5xx / 网络错误 / 响应不可解析 / 拒绝 mcp 服务令牌。"""


class QuantTimeoutError(QuantUnavailableError):
    """请求超时：quant 可能仍在处理（保存可能最终成功、回测任务可能稍后登记）。"""


class QuantClient:
    """quant REST 薄封装（每个方法对应 docs/MCP.md 工具表的一个端点）。"""

    def __init__(self, settings: Settings, client: httpx2.AsyncClient) -> None:
        self._settings = settings
        self._client = client

    async def _request(
        self,
        method: str,
        path: str,
        user_id: str,
        *,
        json_body: Any = None,
        allow_404: bool = False,
        timeout: httpx2.Timeout = QUANT_TIMEOUT,
    ) -> Any:
        headers = {
            "X-Service-Token": self._settings.service_token,
            "X-Service-Name": "mcp",
            "X-User-Id": user_id,
        }
        try:
            resp = await self._client.request(
                method, path, json=json_body, headers=headers, timeout=timeout
            )
        except httpx2.TimeoutException as e:
            logger.warning("quant 请求超时 %s %s：%s", method, path, type(e).__name__)
            raise QuantTimeoutError() from e
        except httpx2.HTTPError as e:
            logger.warning("quant 请求失败 %s %s：%s", method, path, type(e).__name__)
            raise QuantUnavailableError() from e
        if allow_404 and resp.status_code == 404:
            return None
        if resp.status_code >= 500:
            logger.warning("quant 返回 %d：%s %s", resp.status_code, method, path)
            raise QuantUnavailableError()
        if resp.status_code in (401, 403):
            # quant 入站鉴权拒绝的是 mcp 自身（服务令牌缺失/不匹配），不是调用方的错：
            # 不把内部鉴权细节透给 agent，只告警提示运维核对两侧配置
            logger.warning(
                "quant 拒绝 mcp 服务令牌（HTTP %d）：%s %s，请核对 MCP_SERVICE_TOKEN 与 "
                "quant INBOUND_SERVICE_TOKENS",
                resp.status_code,
                method,
                path,
            )
            raise QuantUnavailableError()
        if resp.status_code >= 400:
            try:
                detail = _detail_text(resp.json().get("detail"))
            except (ValueError, AttributeError):
                detail = resp.text
            raise QuantClientError(
                resp.status_code, truncate(detail or f"HTTP {resp.status_code}")
            )
        try:
            return resp.json()
        except ValueError as e:
            logger.warning("quant 响应非 JSON：%s %s", method, path)
            raise QuantUnavailableError() from e

    # ---- 策略 ----

    async def list_strategies(self, user_id: str) -> list[dict]:
        data = await self._request("GET", "/api/strategies", user_id)
        return data if isinstance(data, list) else []

    async def strategy_errors(self, user_id: str) -> list[dict]:
        """本人策略加载错误；quant 旧版本无此端点（404）时按空列表处理。"""
        data = await self._request(
            "GET", "/api/strategies/errors", user_id, allow_404=True
        )
        return data if isinstance(data, list) else []

    async def strategy_guide(self, user_id: str) -> str:
        data = await self._request("GET", "/api/strategies/guide", user_id)
        content = data.get("content") if isinstance(data, dict) else None
        if not isinstance(content, str):
            raise QuantUnavailableError()
        return content

    async def strategy_code(self, user_id: str, strategy_id: str) -> dict:
        return await self._request(
            "GET", f"/api/strategies/{strategy_id}/code", user_id
        )

    async def validate_strategy(self, user_id: str, code: str) -> dict:
        return await self._request(
            "POST", "/api/strategies/validate", user_id, json_body={"code": code}
        )

    async def save_strategy(
        self, user_id: str, code: str, overwrite_id: str | None
    ) -> dict:
        body: dict[str, Any] = {"code": code}
        if overwrite_id:
            body["overwrite_id"] = overwrite_id
        return await self._request(
            "POST", "/api/strategies/save", user_id, json_body=body
        )

    # ---- 回测任务 ----

    async def run_backtest(self, user_id: str, payload: dict) -> dict:
        return await self._request(
            "POST", "/api/backtest/run", user_id, json_body=payload
        )

    async def backtest_task(self, user_id: str, task_id: str) -> dict:
        return await self._request(
            "GET", f"/api/backtest/task/{task_id}", user_id, timeout=TASK_TIMEOUT
        )

    async def cancel_backtest(self, user_id: str, task_id: str) -> dict:
        return await self._request(
            "POST",
            f"/api/backtest/task/{task_id}/cancel",
            user_id,
            timeout=TASK_TIMEOUT,
        )
