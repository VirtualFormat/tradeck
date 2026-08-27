"""OpenBB/yfinance 日K批量适配器：HK/US 全市场日K主源。

海外 yfinance 请求由 ``fetch_openbb`` 自动路由到 Oracle ARM 瘦 OpenBB 节点。
OpenBB historical 支持逗号分隔多 symbol；本适配器按 50 只/批、并发 4，
将 Yahoo symbol 响应映射回 tradeck 规范格式。

用途：TickFlow 当前 Key 无 ``/v1/klines/batch`` 权限（403
NO_KLINE_BATCH_PERMISSION），SDK 又会静默吞掉分片错误并返回空 dict，因此
HK/US 日K改由 OpenBB/yfinance 提供。失败分片隔离，返回已获取部分。
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta
from typing import Any, Awaitable, Callable

from app.datasource.openbb_source import fetch_openbb
from app.markets import to_yahoo_symbol

logger = logging.getLogger(__name__)

# Oracle ARM 节点实测 50 只/批 × 一年约 46 秒；并发 4 时约 1 小时可扫完
# US 1.2 万标的。批量过大容易触发 Yahoo 单请求失败，50 是稳定上限。
_BATCH_SIZE = 50
_CONCURRENCY = 4


def _canonical_symbol(symbol: str, market: str) -> str:
    """OpenBB/Yahoo symbol → tradeck 规范 symbol。"""
    sym = symbol.strip().upper()
    if market == "US":
        return sym[:-3] if sym.endswith(".US") else sym
    if market == "HK":
        code = sym.removesuffix(".HK")
        return f"{code.zfill(5)}.HK"
    return sym


def _request_symbol(symbol: str, market: str) -> str:
    """TickFlow universe symbol → Yahoo/OpenBB symbol。"""
    canonical = _canonical_symbol(symbol, market)
    return to_yahoo_symbol(canonical)


def _parse_date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


async def get_daily_klines_batch(
    symbols: list[str],
    *,
    market: str,
    count: int,
    on_chunk: Callable[[int, int], Any] | None = None,
    on_data: Callable[[dict[str, list[dict]]], Awaitable[None]] | None = None,
) -> dict[str, list[dict]]:
    """批量拉 HK/US 日K，返回 ``{canonical_symbol: rows}``。

    ``count`` 转为自然日窗口（交易日 × 1.7 + 缓冲），请求后按日期升序保留
    最近 count 根。OpenBB 响应每行含 symbol，支持多 symbol 一次请求。

    传入 ``on_data`` 时，每个 50-symbol 分片解析完立即交给调用方写库，不在
    内存累计整个市场（US 全量约 300 万行）；此时返回值仅用于兼容，恒为空。
    """
    if not symbols:
        return {}

    end = date.today() + timedelta(days=1)
    start = end - timedelta(days=max(int(count * 1.7) + 14, 30))
    chunks = [symbols[i : i + _BATCH_SIZE] for i in range(0, len(symbols), _BATCH_SIZE)]
    sem = asyncio.Semaphore(_CONCURRENCY)
    out: dict[str, list[dict]] = {}
    done = 0

    async def fetch_chunk(chunk: list[str]) -> None:
        nonlocal done
        requested = [_request_symbol(symbol, market) for symbol in chunk]
        async with sem:
            data = await fetch_openbb(
                "/equity/price/historical",
                {
                    "provider": "yfinance",
                    "symbol": ",".join(requested),
                    "start_date": start.isoformat(),
                    "end_date": end.isoformat(),
                },
                timeout=120.0,
            )
        grouped: dict[str, list[dict]] = {}
        for row in data.get("results") or []:
            raw_symbol = row.get("symbol")
            if not raw_symbol:
                # 单 symbol 时部分 provider 可能不回 symbol；安全回填。
                raw_symbol = requested[0] if len(requested) == 1 else None
            if not raw_symbol:
                continue
            symbol = _canonical_symbol(str(raw_symbol), market)
            d = _parse_date(row.get("date"))
            close = row.get("close")
            if d is None or close is None:
                continue
            grouped.setdefault(symbol, []).append(
                {
                    "date": d,
                    "open": row.get("open"),
                    "high": row.get("high"),
                    "low": row.get("low"),
                    "close": close,
                    "volume": row.get("volume"),
                    "amount": row.get("amount"),
                }
            )
        chunk_data: dict[str, list[dict]] = {}
        for symbol, rows in grouped.items():
            rows.sort(key=lambda item: item["date"])
            chunk_data[symbol] = rows[-count:]

        if chunk_data:
            if on_data:
                await on_data(chunk_data)
            else:
                out.update(chunk_data)

        if not grouped:
            logger.warning(
                "OpenBB/yfinance %s 日K分片为空（%s 只，%s ~ %s）",
                market,
                len(chunk),
                start,
                end,
            )
        done += len(chunk)
        if on_chunk:
            on_chunk(done, len(symbols))

    await asyncio.gather(*(fetch_chunk(chunk) for chunk in chunks))
    return out
