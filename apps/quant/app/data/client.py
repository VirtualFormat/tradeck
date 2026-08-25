"""data-api 客户端 — quant 进程唯一的数据入口（三条铁律：绝不直连 DB）。

职责：
- POST /api/bars 批量日K：symbols 超 200 自动分批；truncated=true 时按时间窗对半切，
  直到拿全区间数据（合约见 apps/backend/app/api/bars.py）。
- GET as-of 时点查询（analyst consensus / fundamentals metrics）。
- 消费方身份：X-Service-Token（dev 留空内网放行）+ X-Service-Name: quant。
- 失败优雅降级：返回空数据 + 记日志，不抛给调用方（与数据层约定一致）。
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# 与 data-api 合约对齐：symbols 单请求上限 200、limit 上限 50 万
_MAX_SYMBOLS_PER_REQ = 200
_BARS_LIMIT = 500000
# 连接/超时/5xx 指数退避重试；4xx 参数错不重试。
# 注意：连接错误的重试间隔为 1+2+4+8=15s，是「数据源暂时挂掉别雪崩」的取舍；
# CLI 对完全不可达的地址会慢失败（降级为空），可接受。
_MAX_RETRIES = 3


def _headers() -> dict[str, str]:
    headers = {"X-Service-Name": "quant"}
    if settings.SERVICE_TOKEN:
        headers["X-Service-Token"] = settings.SERVICE_TOKEN
    return headers


def _url(path: str) -> str:
    return f"{settings.BACKEND_API_URL.rstrip('/')}{path}"


async def _post_bars_once(
    client: httpx.AsyncClient, symbols: list[str], start: date, end: date
) -> dict[str, Any] | None:
    """单次 /api/bars 请求；重试耗尽返回 None（降级由调用方处理）。"""
    payload = {
        "symbols": symbols,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "limit": _BARS_LIMIT,
    }
    for attempt in range(_MAX_RETRIES + 1):
        try:
            resp = await client.post(_url("/api/bars"), json=payload, headers=_headers())
            if resp.status_code == 200:
                return resp.json()
            if 400 <= resp.status_code < 500:
                logger.error(
                    "/api/bars %s（symbols=%d，%s ~ %s）：%s",
                    resp.status_code, len(symbols), start, end, resp.text[:200],
                )
                return None
            logger.warning("/api/bars %s，第 %d 次重试", resp.status_code, attempt + 1)
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            logger.warning("/api/bars 连接异常（%s），第 %d 次重试", e, attempt + 1)
        await asyncio.sleep(2**attempt)
    logger.error("/api/bars 重试耗尽（symbols=%d，%s ~ %s）", len(symbols), start, end)
    return None


async def _fetch_window(
    client: httpx.AsyncClient, symbols: list[str], start: date, end: date
) -> list[dict[str, Any]]:
    """拉一个 symbol 片在时间窗内的全部日K；truncated 时递归对半切窗。"""
    data = await _post_bars_once(client, symbols, start, end)
    if data is None:
        return []
    bars = data.get("bars", [])
    if not data.get("truncated"):
        return bars
    if start >= end:
        logger.error("/api/bars 单日仍截断（symbols=%d，%s），数据可能不完整", len(symbols), start)
        return bars
    mid = start + (end - start) // 2
    first = await _fetch_window(client, symbols, start, mid)
    second = await _fetch_window(client, symbols, mid + timedelta(days=1), end)
    return first + second


async def fetch_bars(
    symbols: list[str],
    start: date,
    end: date,
    *,
    http_client: httpx.AsyncClient | None = None,
) -> list[dict[str, Any]]:
    """批量拉日K：自动分片 + 截断分窗，返回扁平 bars 列表。

    任一分片失败只损失该分片数据（记日志），不影响其它分片。
    http_client 参数仅供测试注入（MockTransport），生产调用不传。
    """
    all_bars: list[dict[str, Any]] = []

    async def _run(client: httpx.AsyncClient) -> None:
        for i in range(0, len(symbols), _MAX_SYMBOLS_PER_REQ):
            chunk = symbols[i : i + _MAX_SYMBOLS_PER_REQ]
            bars = await _fetch_window(client, chunk, start, end)
            logger.info("fetch_bars 分片 symbols=%d，%s ~ %s，行数=%d", len(chunk), start, end, len(bars))
            all_bars.extend(bars)

    if http_client is not None:
        await _run(http_client)
    else:
        async with httpx.AsyncClient(timeout=60.0) as client:
            await _run(client)
    return all_bars


async def get_json(path: str, params: dict[str, Any]) -> Any:
    """通用 GET（as-of 查询等公开读接口）；失败返回 None。"""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(_url(path), params=params, headers=_headers())
            if resp.status_code == 200:
                return resp.json()
            logger.warning("GET %s → %s：%s", path, resp.status_code, resp.text[:200])
    except (httpx.ConnectError, httpx.TimeoutException) as e:
        logger.warning("GET %s 连接异常：%s", path, e)
    return None
