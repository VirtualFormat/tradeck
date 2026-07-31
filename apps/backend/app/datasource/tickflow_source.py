"""TickFlow 薄门面：日K 稳定源（官方 SDK，自带分片+并发闸+429退避）。

免费档约束（2026-07 对免费 API 实测 + SDK 源码确认）：
- 限频为 IP 级 60 次/分钟；`klines.get` 单只/请求，`klines.batch` 100 只/请求
  （SDK 自动分片 + 并发 5 + 分片级失败隔离）；universe / 指数 / 除权因子均可用；
- 无实时报价、无分钟K、无财务；日K 盘中不实时。
本 adapter 目前仍用 `klines.get` 单只串行（≥6s/次为保守实现，非免费档硬约束），
后续可迁 `klines.batch`。

symbol 已是 `代码.市场后缀`（与 TickFlow 一致），仅做防御性映射（.SS→.SH、港股补零）。

配置了 TICKFLOW_API_KEY 用完整档，否则 TickFlow.free()。
降级：失败返回 []（不抛未捕获异常）。
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date
from typing import Any, Callable

from app.config import settings

logger = logging.getLogger(__name__)

# 串行拉取时每次间隔（秒）。保守值：免费档真实限频为 IP 60 次/分钟，
# 远可放宽；迁 klines.batch（100 只/请求）后本节流可移除
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
    """TickFlow DataFrame → [{date, open, high, low, close, volume, amount}]。"""
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
                "amount": getattr(r, "amount", None),
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


# ─── 批量拉取（借鉴 TickFlow SDK 策略：100 只/片、并发闸、分片失败隔离） ───

_BATCH_CHUNK = 100  # 每片 symbol 数（/v1/klines/batch 上限）
_BATCH_CONCURRENCY = 4  # 并发闸（免费档 IP 60 次/分钟，留足余量）

_async_client: Any = None


def _get_async_client() -> Any:
    """懒加载 AsyncTickFlow 单例（批量接口走 async client）。"""
    global _async_client
    if _async_client is None:
        from tickflow import AsyncTickFlow

        if settings.TICKFLOW_API_KEY:
            _async_client = AsyncTickFlow(api_key=settings.TICKFLOW_API_KEY)
        else:
            _async_client = AsyncTickFlow.free()
    return _async_client


async def get_universe_symbols(universe_id: str) -> list[str]:
    """拉 universe 标的清单（免费档可用）。失败返回 []（降级不抛）。"""
    try:
        detail = await _get_async_client().universes.get(universe_id)
        return list(detail.get("symbols") or [])
    except Exception as e:  # noqa: BLE001
        logger.warning(f"tickflow universe {universe_id} failed: {e}")
        return []


async def get_instrument_names(symbols: list[str]) -> dict[str, str]:
    """批量查标的名（instruments API，500 只/批）。返回 {symbol: name}，失败返回已得部分。"""
    if not symbols:
        return {}
    client = _get_async_client()
    names: dict[str, str] = {}
    for i in range(0, len(symbols), 500):
        chunk = symbols[i : i + 500]
        try:
            insts = await client.instruments.batch(chunk)
            for inst in insts:
                if inst.get("symbol") and inst.get("name"):
                    names[inst["symbol"]] = inst["name"]
        except Exception as e:  # noqa: BLE001
            logger.warning(f"tickflow instruments batch failed ({len(chunk)} symbols): {e}")
    return names


async def get_daily_klines_batch(
    symbols: list[str],
    count: int = 5,
    on_chunk: Callable[[int, int], Any] | None = None,
) -> dict[str, list[dict]]:
    """批量拉多 symbol 日K：100 只/片、并发闸 4、分片失败隔离（借鉴 SDK 策略）。

    - 每片一次 `klines.batch` 请求（≤100 只），SDK 内建 429 指数退避兜底；
    - 失败的片记日志跳过，不影响其他片（缺失 symbol 不出现在结果里）；
    - on_chunk(done_symbols, total_symbols) 每片完成后回调，用于进度上报。

    返回 {tickflow_symbol: [row, ...]}（row 结构同 get_daily_kline）。
    """
    if not symbols:
        return {}
    client = _get_async_client()
    sem = asyncio.Semaphore(_BATCH_CONCURRENCY)
    chunks = [symbols[i : i + _BATCH_CHUNK] for i in range(0, len(symbols), _BATCH_CHUNK)]
    out: dict[str, list[dict]] = {}
    done = 0

    async def fetch_chunk(chunk: list[str]) -> None:
        nonlocal done
        async with sem:
            try:
                dfs = await client.klines.batch(
                    chunk, period="1d", count=count, as_dataframe=True
                )
                for sym, df in dfs.items():
                    rows = _df_to_rows(df)
                    if rows:
                        out[sym] = rows
            except Exception as e:  # noqa: BLE001 — 分片失败隔离
                logger.warning(f"tickflow klines batch chunk failed ({len(chunk)} symbols): {e}")
            done += len(chunk)
            if on_chunk:
                on_chunk(done, len(symbols))

    await asyncio.gather(*(fetch_chunk(c) for c in chunks))
    return out
