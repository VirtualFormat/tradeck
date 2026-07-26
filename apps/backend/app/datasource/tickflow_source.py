"""TickFlow 薄门面：日K 稳定源（官方 SDK，自带分片+并发闸+429退避）。

免费档约束：1 只/次 + IP 限频。故本 adapter **串行 + 自限速**（≥6s/次），
SDK 内建 429 退避兜底。symbol 已是 `代码.市场后缀`（与 TickFlow 一致），
仅做防御性映射（.SS→.SH、港股补零）。

配置了 TICKFLOW_API_KEY 用完整档，否则 TickFlow.free()。
降级：失败返回 []（不抛未捕获异常）。
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

# 免费档 1 只/次 + IP 限频，串行拉取时每次间隔（秒）
_THROTTLE = 6.0

# 串行闸：免费档逐只拉，避免并发触发限频
_lock = asyncio.Lock()

_client: Any = None


def _get_client() -> Any:
    """懒加载 TickFlow 单例（free 档会打印一次提示 banner，只想触发一次）。"""
    global _client
    if _client is None:
        from tickflow import TickFlow

        if settings.TICKFLOW_API_KEY:
            _client = TickFlow(api_key=settings.TICKFLOW_API_KEY)
        else:
            _client = TickFlow.free()
    return _client


def _to_tf_symbol(symbol: str) -> str:
    """tradeck symbol → TickFlow `代码.市场后缀`。

    - 上交所 .SS → .SH（TickFlow 用 .SH）
    - 港股补零到 5 位（0700.HK → 00700.HK）
    - 美股裸代码补 .US（AAPL → AAPL.US）
    - 其余（.SH/.SZ/.BJ）原样
    """
    sym = symbol.strip().upper()
    if sym.endswith(".SS"):
        return sym[:-3] + ".SH"
    if sym.endswith(".HK"):
        code, _, suffix = sym.partition(".")
        return f"{code.zfill(5)}.{suffix}"
    if "." not in sym:
        # 美股裸代码（AAPL/MSFT…）；^指数/=F 商品不迁 TickFlow，不会走到此处
        return f"{sym}.US"
    return sym


def _row_date(v: Any) -> date | None:
    """trade_date（'YYYY-MM-DD'）→ date。"""
    if not v:
        return None
    try:
        return date.fromisoformat(str(v)[:10])
    except (ValueError, TypeError):
        return None


def _df_to_rows(df: Any) -> list[dict]:
    """TickFlow DataFrame → [{date, open, high, low, close, volume}]。"""
    if df is None or df.empty:
        return []
    rows: list[dict] = []
    for r in df.itertuples(index=False):
        d = _row_date(getattr(r, "trade_date", None))
        close = getattr(r, "close", None)
        if d is None or close is None:
            continue
        rows.append(
            {
                "date": d,
                "open": getattr(r, "open", None),
                "high": getattr(r, "high", None),
                "low": getattr(r, "low", None),
                "close": close,
                "volume": getattr(r, "volume", None),
            }
        )
    return rows


async def get_daily_kline(symbol: str, count: int = 365) -> list[dict]:
    """拉单只日K（串行 + 自限速）。失败返回 []（降级不抛）。"""
    tf_symbol = _to_tf_symbol(symbol)

    def fetch() -> Any:
        return _get_client().klines.get(
            tf_symbol, period="1d", count=count, as_dataframe=True
        )

    async with _lock:
        try:
            df = await asyncio.to_thread(fetch)
        except Exception as e:  # noqa: BLE001 — 降级：不抛未捕获异常
            logger.warning(f"tickflow daily kline failed for {symbol} ({tf_symbol}): {e}")
            await asyncio.sleep(_THROTTLE)
            return []
        await asyncio.sleep(_THROTTLE)

    return _df_to_rows(df)
