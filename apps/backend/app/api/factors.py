"""GET /api/factors — 量化批量复权因子：一次拉多标的 adjust_factors 因子序列。

与 POST /api/bars 同源的量化批量接口，面向回测动态复权（引擎内原始价 × 因子合成）：
- 查询参数校验：symbols 1-200 只白名单、日期格式与先后（422 语义同 bars.py）
- 单条 SQL（symbol = ANY + date BETWEEN）+ ORDER BY symbol, date
- 响应为量化契约结构 {factors, count}
- 优雅降级：DB 异常记日志返回空 factors，不 500
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import Field

from app.api._service_auth import ServiceIdentity, quant_access
from app.db import get_pool

logger = logging.getLogger(__name__)

router = APIRouter()

# symbol 白名单与 bars.py / _ensure.valid_symbol 同一规则（大写字母/数字/./-，最长 20）
Symbol = Annotated[str, Field(pattern=r"^[A-Z0-9.\-]{1,20}$")]


@router.get("/api/factors")
async def get_factors(
    symbols: Annotated[list[Symbol], Query(min_length=1, max_length=200)],
    start_date: date,
    end_date: date,
    limit: Annotated[int, Query(ge=1, le=500000)] = 200000,
    identity: ServiceIdentity = Depends(quant_access),
):
    """批量获取复权因子（symbol, date, qfq, hfq），按 symbol, date 升序。

    limit 防 OOM：被截断时 truncated=true（调用方应按时间窗对半切重试，同 /api/bars）。
    重操作接口：已配置 SERVICE_TOKENS 时强制有效 X-Service-Token（未配置则
    内网放行，见 _service_auth.quant_access）。identity 用于消费方审计。
    """
    if end_date < start_date:
        raise HTTPException(status_code=422, detail="end_date 不能早于 start_date")
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT symbol, date, qfq, hfq
                FROM adjust_factors
                WHERE symbol = ANY($1::text[]) AND date BETWEEN $2 AND $3
                ORDER BY symbol ASC, date ASC
                LIMIT $4
                """,
                symbols,
                start_date,
                end_date,
                limit,
            )
    except Exception:  # noqa: BLE001 — 优雅降级：DB 异常返回空 factors，不 500
        logger.exception(
            "/api/factors 查询失败（consumer=%s，symbols=%d 只，%s ~ %s）",
            identity.name,
            len(symbols),
            start_date,
            end_date,
        )
        return {"factors": [], "count": 0, "truncated": False}

    logger.info(
        "/api/factors consumer=%s symbols=%d 行数=%d",
        identity.name,
        len(symbols),
        len(rows),
    )

    factors = [
        {
            "symbol": r["symbol"],
            "date": r["date"].isoformat() if r["date"] else None,
            "qfq": float(r["qfq"]) if r["qfq"] is not None else None,
            "hfq": float(r["hfq"]) if r["hfq"] is not None else None,
        }
        for r in rows
    ]
    return {
        "factors": factors,
        "count": len(factors),
        "truncated": len(rows) >= limit,
    }
