"""OpenBB HTTP 客户端"""
from __future__ import annotations

import httpx
from app.config import settings


async def fetch_openbb(path: str, params: dict | None = None, timeout: float = 10.0) -> dict:
    """调 OpenBB API，返回 JSON dict。失败返回空 results。"""
    url = f"{settings.OPENBB_API_URL}/api/v1{path}"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            res = await client.get(url, params=params)
            if res.status_code != 200:
                return {"results": []}
            text = res.text
            if not text:
                return {"results": []}
            return res.json()
    except Exception:
        return {"results": []}
