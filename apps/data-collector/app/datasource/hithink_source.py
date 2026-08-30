"""同花顺金融数据服务（hithink-finance）薄门面：A 股官方源。

服务地址 https://fuyao.aicubes.cn，REST + `X-api-key` 头鉴权，
契约见 ../Financial-API/docs/api/（错误码表：code==0 成功；4001 限流、
5xxx 服务端异常退避重试；1xxx/2xxx 调用方错误不重试）。

覆盖：A 股行情快照（批量/全市场分页）、历史日K（单只/次、≤10 年、
前/后复权）、估值快照（PE/PB/PS/PCF，100 只/次）、财务报表、
指数/板块、涨停/炸板/连板/龙虎榜等特色数据。无分钟K、无新闻/资金流、
无海外市场。

symbol 与 tradeck 规范格式一致（600519.SH / 000001.SZ / 430047.BJ），
零映射成本。

铁律：优雅降级——任何失败返回 None（由调用方落为空结果），不抛未捕获异常。
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_RETRIES = 3
_BASE_DELAY = 1.0

# 可重试的业务错误码：4001 限流、5xxx 服务端/上游异常
_RETRY_CODES = {4001, 5001, 5002, 5003}


def _available() -> bool:
    """同花顺源是否可用（已配置 API Key）。"""
    return bool(settings.HITHINK_FINANCE_API_KEY)


async def hithink_get(
    path_qs: str,
    *,
    timeout: float = 30.0,
    retries: int = _RETRIES,
) -> dict[str, Any] | None:
    """GET 同花顺 REST API，成功返回信封内 `data`；失败返回 None（降级）。

    path_qs 为路径+查询串（如 /api/a-share/prices/snapshot?thscodes=600519.SH）。

    - HTTP 200 且 code==0 → 返回 data
    - code ∈ {4001, 5xxx} 或网络错误 → 指数退避重试（1/2/4s）
    - 1xxx/2xxx（参数/鉴权错误）→ 不重试，记 warning 返回 None
    """
    if not _available():
        logger.debug("同花顺未配置 HITHINK_FINANCE_API_KEY，跳过调用: %s", path_qs)
        return None

    url = f"{settings.HITHINK_FINANCE_BASE_URL.rstrip('/')}{path_qs}"
    headers = {"X-api-key": settings.HITHINK_FINANCE_API_KEY}
    delay = _BASE_DELAY
    last_err: Any = None

    for attempt in range(retries + 1):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                res = await client.get(url, headers=headers)

            if res.status_code == 200:
                body = res.json()
                code = body.get("code")
                if code == 0:
                    return body.get("data")
                # 业务错误：限流/服务端异常退避重试，其余直接降级
                last_err = f"code={code} {body.get('message')!r} request_id={body.get('request_id')}"
                if code in _RETRY_CODES and attempt < retries:
                    await asyncio.sleep(delay)
                    delay *= 2
                    continue
                logger.warning("同花顺业务错误 %s: %s", path_qs, last_err)
                return None

            # HTTP 层限流/服务端异常退避；4xx 不重试
            if res.status_code in (429, 500, 502, 503, 504):
                last_err = f"HTTP {res.status_code}"
                if attempt < retries:
                    await asyncio.sleep(delay)
                    delay *= 2
                    continue
            logger.warning("同花顺 HTTP 错误 %s: %s", path_qs, res.status_code)
            return None

        except (httpx.HTTPError, ValueError) as e:
            last_err = e
            if attempt < retries:
                await asyncio.sleep(delay)
                delay *= 2
                continue
            logger.warning("同花顺请求失败 %s: %s", path_qs, e)
            return None

    logger.warning("同花顺重试耗尽 %s: %s", path_qs, last_err)
    return None


# ---------------------------------------------------------------------------
# 业务封装：按 tradeck 常用场景提供语义化函数
# ---------------------------------------------------------------------------


async def get_quotes_snapshot(thscodes: list[str]) -> list[dict[str, Any]]:
    """批量 A 股行情快照。thscode 与 tradeck symbol 一致，直接透传。

    返回 item 列表（无 name 字段，需中文名走 search/list）；失败返回 []。
    """
    if not thscodes:
        return []
    data = await hithink_get(
        f"/api/a-share/prices/snapshot?thscodes={','.join(thscodes)}"
    )
    if not data:
        return []
    return data.get("item") or []


async def get_daily_kline(
    thscode: str,
    start_ms: int,
    end_ms: int,
    *,
    adjust: str = "forward",
) -> list[dict[str, Any]]:
    """单只 A 股历史日K（≤10 年窗口）。adjust: none/forward/backward。

    返回 item 列表（date_ms/open/high/low/close/volume/turnover）；失败返回 []。
    """
    data = await hithink_get(
        f"/api/a-share/prices/historical?thscode={thscode}"
        f"&interval=1d&start={start_ms}&end={end_ms}&adjust={adjust}"
    )
    if not data:
        return []
    return data.get("item") or []


async def get_valuations_snapshot(thscodes: list[str]) -> list[dict[str, Any]]:
    """批量 A 股估值快照（pe_ttm/pe_mrq/pb_mrq/ps_ttm/pcf_ttm，≤100 只/次）。

    返回 item 列表（含 name）；失败返回 []。
    """
    if not thscodes:
        return []
    data = await hithink_get(
        f"/api/a-share/valuations/snapshot?thscodes={','.join(thscodes)}"
    )
    if not data:
        return []
    return data.get("item") or []


async def search_ticker(q: str, *, limit: int = 5) -> list[dict[str, Any]]:
    """标的检索/消歧（名称/代码 → thscode）。失败返回 []。"""
    data = await hithink_get(f"/api/meta/tickers/search?q={q}&limit={limit}")
    if not data:
        return []
    return data.get("item") or []


async def get_limit_up_pool(
    *,
    date_ms: int | None = None,
    page: int = 1,
    size: int = 50,
) -> dict[str, Any] | None:
    """涨停/连板股票池。返回 {timestamp, pagination, item[]}；失败返回 None。"""
    qs = f"/api/a-share/special-data/limit-up-pool?page={page}&size={size}"
    if date_ms is not None:
        qs += f"&date_ms={date_ms}"
    return await hithink_get(qs)


async def get_adjustment_events(
    thscode: str,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[dict[str, Any]] | None:
    """获取单只 A 股公司行为事件；失败返回 None，成功空结果返回 []。"""
    qs = (
        "/api/a-share/corporate-actions/adjustment-factors"
        f"?thscode={thscode}"
    )
    if date_from:
        qs += f"&from={date_from.isoformat()}"
    if date_to:
        qs += f"&to={date_to.isoformat()}"
    data = await hithink_get(qs)
    if data is None:
        return None
    return data.get("item") or []


async def scan_adjustment_events(
    thscodes: list[str],
    *,
    date_from: date,
    date_to: date,
    concurrency: int = 8,
    on_progress: Any | None = None,
) -> tuple[dict[str, list[dict[str, Any]]], int]:
    """并发扫描多只 A 股最近事件，返回 ``({symbol: events}, failed)``。

    REST 暂无全市场增量端点，因此每日只扫短时间窗。使用一个共享 HTTP 客户端，
    避免为约 5,500 只标的反复建 TLS 连接；4001/5xxx 有界退避。
    """
    if not _available() or not thscodes:
        return {}, len(thscodes)

    base = settings.HITHINK_FINANCE_BASE_URL.rstrip("/")
    headers = {"X-api-key": settings.HITHINK_FINANCE_API_KEY}
    sem = asyncio.Semaphore(concurrency)
    events_by_symbol: dict[str, list[dict[str, Any]]] = {}
    failed = 0
    done = 0

    async with httpx.AsyncClient(
        timeout=30.0,
        headers=headers,
        limits=httpx.Limits(max_connections=concurrency, max_keepalive_connections=concurrency),
    ) as client:

        async def fetch_one(symbol: str) -> None:
            nonlocal failed, done
            params = {
                "thscode": symbol,
                "from": date_from.isoformat(),
                "to": date_to.isoformat(),
            }
            delay = _BASE_DELAY
            async with sem:
                for attempt in range(_RETRIES + 1):
                    try:
                        res = await client.get(
                            f"{base}/api/a-share/corporate-actions/adjustment-factors",
                            params=params,
                        )
                        body = res.json() if res.status_code == 200 else {}
                        code = body.get("code")
                        if res.status_code == 200 and code == 0:
                            items = (body.get("data") or {}).get("item") or []
                            if items:
                                events_by_symbol[symbol] = items
                            break
                        # 公司行为端点用 3002 表示该标的在请求窗口内没有事件，
                        # 属正常空结果，不应计入失败或把每日任务标成 partial。
                        if res.status_code == 200 and code == 3002:
                            break
                        retryable = (
                            res.status_code in (429, 500, 502, 503, 504)
                            or code in _RETRY_CODES
                        )
                        if retryable and attempt < _RETRIES:
                            await asyncio.sleep(delay)
                            delay *= 2
                            continue
                        failed += 1
                        break
                    except (httpx.HTTPError, ValueError):
                        if attempt < _RETRIES:
                            await asyncio.sleep(delay)
                            delay *= 2
                            continue
                        failed += 1
                done += 1
                if on_progress:
                    on_progress(done, len(thscodes))

        await asyncio.gather(*(fetch_one(symbol) for symbol in thscodes))

    return events_by_symbol, failed


# ---------------------------------------------------------------------------
# Market Dumps：全市场 Parquet 导出（签名 URL → 下载 → 返回字节流）
# ---------------------------------------------------------------------------


async def get_dump_download_url(dump_type: str) -> str | None:
    """获取 Market Dump 的 S3 预签名下载 URL（约 5 分钟有效，拿到立刻下载）。

    dump_type: daily-k（全市场 10 年）/ daily-k-10d（近 10 交易日）/
    adjustment-factors（全市场复权事件）。失败返回 None。
    """
    data = await hithink_get(f"/api/dump/market-dumps/{dump_type}/download-url")
    if not data:
        return None
    return data.get("presigned_url")


async def download_dump(dump_type: str, *, timeout: float = 600.0) -> bytes | None:
    """签名 + 下载 Market Dump Parquet，返回文件字节；失败返回 None（降级）。

    全量 daily-k 约 170MB/~945 万行，下载需 1-3 分钟，调用方注意 timeout
    与内存占用；daily-k-10d / adjustment-factors 均 <2MB。
    """
    url = await get_dump_download_url(dump_type)
    if not url:
        return None
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            res = await client.get(url)
        if res.status_code != 200:
            logger.warning("同花顺 dump 下载失败 %s: HTTP %s", dump_type, res.status_code)
            return None
        return res.content
    except httpx.HTTPError as e:
        logger.warning("同花顺 dump 下载异常 %s: %s", dump_type, e)
        return None
