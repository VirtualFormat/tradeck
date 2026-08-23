"""分钟K 采集 job（4.2a-0 冷层先行）：每日拉当日分钟K，直写冷层 Parquet。

链路：yfinance 1m（库直调）→ quality_gate（minute_bars 质量闸）→
      ColdStorage 写 Parquet 落冷层（year/market 分区 + 文件内 (symbol,ts) 排序）。

范围与现状（D1 实测 2026-08-22）：
- US/HK：yfinance 1m（仅近 7 天窗口）——每日采当日，漏采即永久丢失，缺口检测是生死线。
- A股：免费源（TickFlow 分钟K 付费档 / akshare 东财分钟接口本地被封）暂不可采，
  待付费档或 QMT/iFinD（D2/D3/D4）后接入。

纪律：ts 统一存 UTC epoch 秒；每日幂等（重跑覆盖同分区文件）；本地 yfinance
常被限流（已知坑 #5）——限流时优雅降级记日志，环境正常（VPS）时正常采集。
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timezone
from typing import Any

from app.cold_storage import get_cold_storage
from app.quality import quality_gate

logger = logging.getLogger(__name__)


def _minute_symbols() -> dict[str, list[str]]:
    """按市场分组待采标的（仅 US/HK，A股待付费源）。"""
    from app.constants import TRACKED_SYMBOLS
    from app.markets import pick_market

    groups: dict[str, list[str]] = {"US": [], "HK": []}
    for s in TRACKED_SYMBOLS:
        m = pick_market(s)
        if m in groups:
            groups[m].append(s)
    return groups


def _fetch_1m(symbols: list[str]) -> Any:
    """同步拉多只标的当日 1m（yfinance 库直调）。限流/失败抛异常由调用方降级。"""
    import yfinance as yf
    from app.markets import to_yahoo_symbol

    yahoo = [to_yahoo_symbol(s) for s in symbols]
    # period='1d' 当日分钟K；auto_adjust=False 保留原始 OHLC（复权另算）
    return yf.download(
        yahoo, interval="1m", period="1d", progress=False, auto_adjust=False
    )


def _df_to_rows(df: Any, symbols: list[str], market: str, day: date) -> list[dict[str, Any]]:
    """yfinance 多标的 MultiIndex DataFrame → 分钟K dict 行（ts 为 UTC epoch 秒）。"""
    import pandas as pd

    from app.markets import to_yahoo_symbol

    if df is None or len(df) == 0:
        return []

    rows: list[dict[str, Any]] = []
    is_multi = isinstance(df.columns, pd.MultiIndex)

    # DataFrame 列是 yahoo 格式（港股 4 位、.SH→.SS），需转换后取数；
    # 写库的 symbol 仍是规范格式（行内 sym），仅取数时用 yahoo 格式定位列
    for sym in symbols:
        yahoo_sym = to_yahoo_symbol(sym)
        try:
            sub = df.xs(yahoo_sym, level=1, axis=1) if is_multi else df
        except (KeyError, ValueError):
            continue
        for ts, r in sub.iterrows():
            close = r.get("Close")
            if close is None or (isinstance(close, float) and close != close):  # NaN
                continue
            # 时间戳统一 UTC epoch 秒（yfinance 返回带交易所时区的 DatetimeIndex）
            if hasattr(ts, "tz_convert"):
                ts_utc = ts.tz_convert("UTC") if ts.tzinfo else ts.tz_localize("UTC")
                epoch = int(ts_utc.timestamp())
            else:
                epoch = int(pd.Timestamp(ts, tz="UTC").timestamp())
            rows.append(
                {
                    "symbol": sym,
                    "market": market,
                    "ts": epoch,
                    "open": r.get("Open"),
                    "high": r.get("High"),
                    "low": r.get("Low"),
                    "close": close,
                    "volume": r.get("Volume"),
                    "amount": None,  # yfinance 1m 无成交额，留 None
                }
            )
    return rows


async def fetch_and_store_minute_kline(
    market: str, symbols: list[str], day: date
) -> int:
    """拉单市场当日分钟K → 质量闸 → 冷层。返回落冷层条数。"""
    if not symbols:
        return 0

    # ① 拉取（限流/失败优雅降级：记日志返回 0，不抛）
    try:
        df = await asyncio.to_thread(_fetch_1m, symbols)
    except Exception as e:  # noqa: BLE001 — yfinance 限流/网络，优雅降级
        logger.warning(f"minute_kline {market} 拉取失败（{type(e).__name__}: {e}）")
        return 0

    rows = _df_to_rows(df, symbols, market, day)
    if not rows:
        logger.warning(f"minute_kline {market} {day} 无数据（{len(symbols)} 只）")
        return 0

    # ② 质量闸（OHLC 自洽 + 非负；分钟K 不落库表，quarantine 留痕于 quality 层）
    accepted = await quality_gate("minute_bars", rows)
    if not accepted:
        return 0

    # ③ 冷层：year/market/date 分区 + 文件内 (symbol,ts) 排序；幂等覆盖当日文件
    key = f"minute_bars/year={day.year}/market={market}/date={day.isoformat()}/part-000.parquet"
    cs = get_cold_storage()
    await asyncio.to_thread(cs.write_parquet, key, accepted, sort_by=["symbol", "ts"])
    logger.info(f"minute_kline {market} {day}: {len(accepted)} rows → {key}")
    return len(accepted)


async def run_minute_kline_job(day: date | None = None) -> dict[str, int]:
    """每日分钟K 采集：US/HK 各市场采当日。返回各市场落冷层条数。"""
    logger.info("=== minute kline job start ===")
    day = day or datetime.now(timezone.utc).date()
    groups = _minute_symbols()
    counts: dict[str, int] = {}
    for market, symbols in groups.items():
        counts[market] = await fetch_and_store_minute_kline(market, symbols, day)
    logger.info(
        "=== minute kline job done: "
        + ", ".join(f"{m}={c}" for m, c in counts.items())
        + " ==="
    )
    return counts
