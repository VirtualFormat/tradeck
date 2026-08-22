"""OpenBB HTTP 客户端"""
from __future__ import annotations

import httpx
from app.config import settings

# 需要出海访问的 provider —— 命中则路由到海外节点（韩国瘦 OpenBB）
OVERSEAS_PROVIDERS = {"yfinance", "sec", "fred", "federal_reserve", "oecd"}

# 海外链路（跨境 + CF）延迟更高，用更宽松的默认超时
OVERSEAS_TIMEOUT = 20.0


async def fetch_openbb(path: str, params: dict | None = None, timeout: float | None = None) -> dict:
    """调 OpenBB API，返回 JSON dict。失败返回空 results。

    按 params["provider"] 路由：海外 provider 且配置了海外节点时走韩国节点
    （带 X-OpenBB-Token 头）；否则走国内 OPENBB_API_URL（akshare / 未标注 /
    未配置海外节点）。海外链路断只返回空 results，不回退国内。
    """
    provider = (params or {}).get("provider")
    use_overseas = (
        provider in OVERSEAS_PROVIDERS and bool(settings.OPENBB_OVERSEAS_API_URL)
    )

    if use_overseas:
        base = settings.OPENBB_OVERSEAS_API_URL
        headers = (
            {"X-OpenBB-Token": settings.OPENBB_OVERSEAS_TOKEN}
            if settings.OPENBB_OVERSEAS_TOKEN
            else None
        )
        effective_timeout = timeout if timeout is not None else OVERSEAS_TIMEOUT
    else:
        base = settings.OPENBB_API_URL
        headers = None
        effective_timeout = timeout if timeout is not None else 10.0

    url = f"{base}/api/v1{path}"
    try:
        async with httpx.AsyncClient(timeout=effective_timeout) as client:
            res = await client.get(url, params=params, headers=headers)
            if res.status_code != 200:
                return {"results": []}
            text = res.text
            if not text:
                return {"results": []}
            return res.json()
    except Exception:
        return {"results": []}
