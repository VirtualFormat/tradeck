"""GET /api/bars/minute — 量化/回测批量分钟K：一次拉多标的分钟级行情（ClickHouse 温层）。

与 POST /api/bars/minute（minute_bars.py，读本地 Parquet 池）并存：本路由走
CH HTTP 8123（库 tradeck，表 minute_bars，ts 为 UTC），data-api 只读 CH，绝不写。

- 参数校验（pydantic）：symbols 1-50 只白名单、日期格式与先后、窗口 ≤ 31 天防大查询、
  limit 上限防 OOM（与 POST /api/bars 同一套校验风格）
- 单条 SQL（symbol IN + ts 半开区间 [start, end+1d)）+ ORDER BY symbol, ts，LIMIT 截断；
  全部值经 CH HTTP 的 param_xxx 查询参数绑定，不做字符串拼接
- 响应为扁平 JSON 数组（与全站 GET 读路由主流风格一致，区别于 POST /api/bars 的
  {bars,count,truncated} 包装）；是否被 limit 截断用 X-Truncated 响应头标记
- 优雅降级：CH 不可达/查询异常记 logger.warning 返回 []（200），不 500
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date, timedelta
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Response

from app.api._service_auth import ServiceIdentity, quant_access
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter()

# symbol 白名单与 bars.py / _ensure.valid_symbol 同一规则（大写字母/数字/./-，最长 20）
_SYMBOL_RE = re.compile(r"^[A-Z0-9.\-]{1,20}$")
_MAX_SYMBOLS = 50
_MAX_WINDOW_DAYS = 31  # 分钟K 行密度高，单次查询窗口收紧（POST 版 366 天走 Parquet）

# CH 查询超时：分钟K 大区间可能扫几十万行，给足但不无限等
_CH_TIMEOUT = httpx.Timeout(30.0, connect=5.0)


def _parse_symbols(raw: str) -> list[str]:
    """逗号分隔 symbols → 大写、去重保序；数量/字符非法抛 ValueError（→ 422）。"""
    symbols = list(dict.fromkeys(s.strip().upper() for s in raw.split(",") if s.strip()))
    if not 1 <= len(symbols) <= _MAX_SYMBOLS:
        raise ValueError(f"symbols 数量须在 1-{_MAX_SYMBOLS} 只之间")
    if not all(_SYMBOL_RE.fullmatch(s) for s in symbols):
        raise ValueError("symbols 含非法字符（仅允许大写字母/数字/./-，最长 20）")
    return symbols


def _validate_window(start: date, end: date) -> None:
    if end < start:
        raise ValueError("end_date 不能早于 start_date")
    if (end - start).days > _MAX_WINDOW_DAYS:
        raise ValueError(f"分钟 K 单次查询窗口不能超过 {_MAX_WINDOW_DAYS} 天")


async def _query_clickhouse(
    symbols: list[str], start: date, end: date, limit: int
) -> list[dict]:
    """CH HTTP 8123 查询（JSONEachRow）；全部值走 param_xxx 绑定，禁字符串拼接。

    ts 半开区间 [start 00:00, end+1 天 00:00)（UTC），含 end 当天全部分钟。
    """
    query = (
        f"SELECT symbol, market, ts, open, high, low, close, volume, amount "
        f"FROM {settings.CLICKHOUSE_DATABASE}.minute_bars "
        f"WHERE symbol IN {{symbols:Array(String)}} "
        f"AND ts >= {{start:DateTime}} AND ts < {{end:DateTime}} "
        f"ORDER BY symbol ASC, ts ASC "
        f"LIMIT {{limit:UInt32}} "
        f"FORMAT JSONEachRow"
    )
    async with httpx.AsyncClient(timeout=_CH_TIMEOUT) as client:
        resp = await client.post(
            settings.CLICKHOUSE_URL + "/",
            params={
                # CH Array(String) 参数只认单引号字面量（['a','b']），
                # 不能用 json.dumps 的双引号；symbol 已过白名单正则，无引号注入面
                "param_symbols": "[" + ",".join(f"'{s}'" for s in symbols) + "]",
                "param_start": f"{start.isoformat()} 00:00:00",
                "param_end": f"{(end + timedelta(days=1)).isoformat()} 00:00:00",
                "param_limit": str(limit),
            },
            content=query,
            headers={"Content-Type": "text/plain; charset=utf-8"},
        )
    resp.raise_for_status()
    return [json.loads(line) for line in resp.text.splitlines() if line.strip()]


@router.get("/api/bars/minute")
async def get_bars_minute(
    response: Response,
    symbols: Annotated[str, Query(description="逗号分隔标的，1-50 只")],
    start_date: date,
    end_date: date,
    limit: Annotated[int, Query(ge=1, le=200000)] = 100000,
    identity: ServiceIdentity = Depends(quant_access),
) -> list[dict]:
    """批量获取分钟 K 线，按 symbol, ts 升序；被 limit 截断时 X-Truncated: true。

    重操作接口：与 POST /api/bars 同挂 quant_access（已配置 SERVICE_TOKENS 时
    强制有效 X-Service-Token；未配置则内网放行）。identity 用于消费方审计。

    优雅降级：CH 不可达/查询异常返回 []（200），记 logger.warning，不 500。
    """
    # 手写校验（ValueError → HTTPException 422），保证与 POST /api/bars 同款 422 语义
    try:
        symbol_list = _parse_symbols(symbols)
        _validate_window(start_date, end_date)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    try:
        rows = await _query_clickhouse(symbol_list, start_date, end_date, limit)
    except Exception as exc:  # noqa: BLE001 — 优雅降级：CH 不可达/查询异常返回 []，不 500
        logger.warning(
            "/api/bars/minute CH 查询失败，降级返回空（consumer=%s，symbols=%d 只，"
            "%s ~ %s）：%s",
            identity.name,
            len(symbol_list),
            start_date,
            end_date,
            exc,
        )
        return []

    logger.info(
        "/api/bars/minute consumer=%s symbols=%d 行数=%d",
        identity.name,
        len(symbol_list),
        len(rows),
    )
    response.headers["X-Truncated"] = "true" if len(rows) >= limit else "false"
    # CH DateTime 已是 "YYYY-MM-DD HH:MM:SS"（UTC）字符串，直接透传，
    # 与现有 API 的日期字符串风格一致
    return rows
