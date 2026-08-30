"""POST /api/bars — 量化/回测批量日K：一次拉多标的历史行情（daily_prices）。

与单 symbol 的 GET /api/historical 不同，本接口面向批量消费：
- 请求体校验（pydantic）：symbols 1-200 只白名单、日期格式与先后、limit 上限防 OOM
- 单条 SQL（symbol = ANY + date BETWEEN）+ ORDER BY symbol, date，LIMIT 截断
- 响应为量化契约结构 {bars, count, truncated}（允许顶层 bars 数组）
- 优雅降级：DB 异常记日志返回空 bars，不 500
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator

from app.api._service_auth import ServiceIdentity, quant_access
from app.db import get_pool

logger = logging.getLogger(__name__)

router = APIRouter()

# symbol 白名单与 _ensure.valid_symbol 同一规则（大写字母/数字/./-，最长 20）
Symbol = Annotated[str, Field(pattern=r"^[A-Z0-9.\-]{1,20}$")]


class BarsRequest(BaseModel):
    """批量日K请求体。"""

    symbols: Annotated[list[Symbol], Field(min_length=1, max_length=200)]
    start_date: date
    end_date: date
    limit: int = Field(default=100000, ge=1, le=500000)  # 防 OOM 上限
    # 复权：""=原始 / qfq 前复权 / hfq 后复权（PG 原始价 × adjust_factors 因子）
    adjust: Literal["", "qfq", "hfq"] = ""

    @field_validator("end_date")
    @classmethod
    def _end_not_before_start(cls, v: date, info):
        start = info.data.get("start_date")
        if start is not None and v < start:
            raise ValueError("end_date 不能早于 start_date")
        return v


@router.post("/api/bars")
async def post_bars(
    req: BarsRequest,
    identity: ServiceIdentity = Depends(quant_access),
):
    """批量获取日 K 线，按 symbol, date 升序；被 limit 截断时 truncated=true。

    adjust="" 返回原始价；adjust=qfq/hfq 返回对应复权价（PG 原始 OHLC ×
    adjust_factors 因子；volume/amount 不复权）。缺因子的行仍返回原始价，但响应
    ``adjustment`` 会明确标记覆盖率和缺失标的，不再静默冒充完整复权结果。

    重操作接口：已配置 SERVICE_TOKENS 时强制有效 X-Service-Token（未配置则
    内网放行，见 _service_auth.quant_access）。identity 用于消费方审计。
    """
    # 复权：qfq/hfq 时 LEFT JOIN 因子表，原始价不 JOIN（零开销）
    factor_col = f"f.{req.adjust}" if req.adjust in ("qfq", "hfq") else None
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            if factor_col:
                rows = await conn.fetch(
                    f"""
                    SELECT p.symbol, p.date, p.open, p.high, p.low, p.close,
                           p.volume, p.amount, {factor_col} AS factor
                    FROM daily_prices p
                    LEFT JOIN adjust_factors f
                      ON f.symbol = p.symbol AND f.date = p.date
                    WHERE p.symbol = ANY($1::text[]) AND p.date BETWEEN $2 AND $3
                    ORDER BY p.symbol ASC, p.date ASC
                    LIMIT $4
                    """,
                    req.symbols,
                    req.start_date,
                    req.end_date,
                    req.limit,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT symbol, date, open, high, low, close, volume, amount
                    FROM daily_prices
                    WHERE symbol = ANY($1::text[]) AND date BETWEEN $2 AND $3
                    ORDER BY symbol ASC, date ASC
                    LIMIT $4
                    """,
                    req.symbols,
                    req.start_date,
                    req.end_date,
                    req.limit,
                )
    except Exception:  # noqa: BLE001 — 优雅降级：DB 异常返回空 bars，不 500
        logger.exception(
            "/api/bars 查询失败（consumer=%s，symbols=%d 只，%s ~ %s）",
            identity.name,
            len(req.symbols),
            req.start_date,
            req.end_date,
        )
        return {"bars": [], "count": 0, "truncated": False}

    logger.info(
        "/api/bars consumer=%s symbols=%d 行数=%d",
        identity.name,
        len(req.symbols),
        len(rows),
    )

    def _adj(value, factor):
        """原始价 × 因子（qfq/hfq）；无因子或空值返回原始值。"""
        if value is None or factor is None:
            return value
        return round(float(value) * float(factor), 4)

    bars = [
        {
            "symbol": r["symbol"],
            "date": r["date"].isoformat() if r["date"] else None,
            "open": _adj(float(r["open"]) if r["open"] is not None else None, r.get("factor")),
            "high": _adj(float(r["high"]) if r["high"] is not None else None, r.get("factor")),
            "low": _adj(float(r["low"]) if r["low"] is not None else None, r.get("factor")),
            "close": _adj(float(r["close"]) if r["close"] is not None else None, r.get("factor")),
            "volume": int(r["volume"]) if r["volume"] is not None else None,
            "amount": float(r["amount"]) if r["amount"] is not None else None,
        }
        for r in rows
    ]
    adjustment = {
        "requested": req.adjust or "none",
        "complete": True,
        "factor_rows": 0,
        "missing_rows": 0,
        "missing_symbols": [],
    }
    if factor_col:
        factor_rows = sum(1 for row in rows if row.get("factor") is not None)
        missing_symbols = sorted(
            {
                row["symbol"]
                for row in rows
                if row.get("factor") is None
            }
        )
        adjustment.update(
            {
                "complete": factor_rows == len(rows),
                "factor_rows": factor_rows,
                "missing_rows": len(rows) - factor_rows,
                "missing_symbols": missing_symbols,
            }
        )
    return {
        "bars": bars,
        "count": len(bars),
        "truncated": len(rows) >= req.limit,
        "adjustment": adjustment,
    }
