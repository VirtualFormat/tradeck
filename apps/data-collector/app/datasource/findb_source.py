"""findb 金融数据 API 门面（主数据源，直连取数）。

findb（https://api.jiucaicat.icu）：A股全市场 + 复权(qfq/hfq) + 分钟K + 85 表，
只读、仅 GET、Bearer 鉴权。本文档见飞书《findb 金融数据 API · 接入与数据说明》。

关键坑（文档第 8/9 节）：
- **写锁返回 HTTP 200 但 body 带 error 键**——不能只看状态码，要查 error 后退避重试。
- **429 限流 / 503 写锁**——退避重试（1/2/4/8s）。
- **「最近 N 根」必须 order=desc**（默认 asc + limit 返回最旧 N 根）。
- 密钥一人一设备一把（FINDB_KEY 走环境变量；为空则本源不可用，优雅降级返回空）。

铁律：优雅降级——任何失败返回空结果（{"data": []} / 空 list），不抛未捕获异常。
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_RETRIES = 4
_BASE_DELAY = 1.0
# 所有 findb API 调用共享节流闸。单 key 是全进程配额，不允许各 job 各自并发。
_MIN_INTERVAL = 1.05
_request_lock = asyncio.Lock()
_last_request_at = 0.0


async def _throttled_get(
    client: httpx.AsyncClient,
    url: str,
    headers: dict[str, str],
) -> httpx.Response:
    global _last_request_at
    async with _request_lock:
        wait = _MIN_INTERVAL - (time.monotonic() - _last_request_at)
        if wait > 0:
            await asyncio.sleep(wait)
        try:
            return await client.get(url, headers=headers)
        finally:
            _last_request_at = time.monotonic()


def _available() -> bool:
    """findb 是否可用（已配置密钥）。"""
    return bool(settings.FINDB_KEY)


async def findb_get(
    path_qs: str,
    *,
    timeout: float = 60.0,
    retries: int = _RETRIES,
) -> Any:
    """GET findb，返回解析后的 JSON。写锁/限流自动退避重试；失败返回 None（降级）。

    path_qs 为路径+查询串（如 /api/bars?code=600036.SH&freq=daily&adjust=hfq）。
    """
    if not _available():
        logger.debug("findb 未配置 FINDB_KEY，跳过调用: %s", path_qs)
        return None

    url = f"{settings.FINDB_BASE_URL.rstrip('/')}{path_qs}"
    headers = {"Authorization": f"Bearer {settings.FINDB_KEY}"}
    delay = _BASE_DELAY
    last_err: Any = None

    for attempt in range(retries + 1):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                res = await _throttled_get(client, url, headers)

            # 写锁：HTTP 200 但 body 带 error 键 → 退避重试
            if res.status_code == 200:
                data = res.json()
                if isinstance(data, dict) and "error" in data:
                    last_err = data["error"]
                    if attempt < retries:
                        await asyncio.sleep(delay)
                        delay *= 2
                        continue
                    logger.warning(f"findb 持续写锁 {path_qs}: {last_err}")
                    return None
                return data

            # 限流/写锁/配额：429/503 → 退避重试；401/403 不重试（密钥/权限问题）
            if res.status_code in (429, 503):
                last_err = f"HTTP {res.status_code}"
                if attempt < retries:
                    await asyncio.sleep(delay)
                    delay *= 2
                    continue
                logger.warning(f"findb 持续繁忙 {path_qs}: {last_err}")
                return None

            logger.warning(f"findb {path_qs} HTTP {res.status_code}: {res.text[:200]}")
            return None

        except Exception as e:  # noqa: BLE001 — 网络/解析异常，优雅降级
            last_err = e
            if attempt < retries:
                await asyncio.sleep(delay)
                delay *= 2
                continue
            logger.warning(f"findb {path_qs} 重试 {retries} 次仍失败: {last_err}")
            return None

    return None


# ── 便捷封装（对应 findb 核心端点）─────────────────────────


async def fetch_bars(
    code: str,
    *,
    freq: str = "daily",
    adjust: str = "",
    start: str | None = None,
    end: str | None = None,
    order: str = "asc",
    limit: int | None = None,
    timeout: float = 60.0,
    retries: int = _RETRIES,
) -> list[dict]:
    """取 K 线（/api/bars）。失败/无数据返回空 list。

    code 带后缀（600036.SH / AAPL.US / 00700.HK / RB9999.SHFE）。
    freq: 1min/5min/15min/30min/60min/daily。adjust: 空/qfq/hfq。
    「最近 N 根」须 order="desc"（调用方负责，这里不强制）。
    """
    qs = f"/api/bars?code={code}&freq={freq}&order={order}"
    if adjust:
        qs += f"&adjust={adjust}"
    if start:
        qs += f"&start={start}"
    if end:
        qs += f"&end={end}"
    if limit:
        qs += f"&limit={limit}"
    data = await findb_get(qs, timeout=timeout, retries=retries)
    if not isinstance(data, dict):
        return []
    return data.get("data") or []


async def fetch_bars_batch(
    codes: list[str],
    *,
    freq: str,
    start: str,
    end: str,
    order: str = "asc",
    timeout: float = 90.0,
    retries: int = _RETRIES,
) -> list[dict]:
    """批量取 K 线（服务端限制每批 <=50 只）；失败返回空 list。

    对同一 key 仍经过全局节流闸。响应 data 为扁平行，每行自带 code。
    """
    if not codes:
        return []
    if len(codes) > 50:
        raise ValueError("findb batch bars 每批最多 50 只")
    qs = (
        f"/api/bars?codes={','.join(codes)}&freq={freq}"
        f"&start={start}&end={end}&order={order}"
    )
    data = await findb_get(qs, timeout=timeout, retries=retries)
    if not isinstance(data, dict):
        return []
    if data.get("truncated"):
        logger.warning("findb batch bars 被截断: %s %s~%s", freq, start, end)
    return data.get("data") or []


async def fetch_table(
    name: str,
    *,
    cols: str | None = None,
    col: str | None = None,
    val: str | None = None,
    sort: str | None = None,
    order: str | None = None,
    limit: int | None = None,
) -> list[dict]:
    """通用取数（/api/table，财务/资金面/情绪/宏观等 85 表）。失败返回空 list。"""
    qs = f"/api/table?name={name}"
    if cols:
        qs += f"&cols={cols}"
    if col and val is not None:
        qs += f"&col={col}&val={val}"
    if sort:
        qs += f"&sort={sort}"
    if order:
        qs += f"&order={order}"
    if limit:
        qs += f"&limit={limit}"
    data = await findb_get(qs)
    if isinstance(data, dict):
        return data.get("data") or []
    if isinstance(data, list):
        return data
    return []


async def fetch_symbols(asset: str | None = None) -> list[dict]:
    """标的列表（/api/symbols）。asset: stock/etf/future/us_stock/hk_stock/index/..."""
    qs = "/api/symbols" + (f"?asset={asset}" if asset else "")
    data = await findb_get(qs)
    if isinstance(data, dict):
        return data.get("data") or data.get("symbols") or []
    if isinstance(data, list):
        return data
    return []


async def fetch_coverage(code: str) -> dict:
    """标的各频率覆盖区间（/api/coverage，取数前确认避免取空）。失败返回空 dict。"""
    data = await findb_get(f"/api/coverage?code={code}")
    return data if isinstance(data, dict) else {}


async def health() -> bool:
    """探活（/health，不消耗配额）。True = 连通且密钥有效。"""
    data = await findb_get("/health", timeout=10.0, retries=1)
    return isinstance(data, dict) and data.get("status") == "ok"
