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
        if m not in groups:
            continue
        # 健壮性：港股规范码须为 5 位（不足 5 位的原始码经 to_yahoo_symbol 的
        # lstrip('0').zfill(4) 可能产生非法 yahoo ticker，导致查询不到数据）。
        # 规范约定港股 5 位补零，这里断言兜底，异常代码记日志跳过。
        if m == "HK":
            code = s.split(".")[0]
            if len(code) != 5:
                logger.warning(f"minute_kline 跳过非法港股代码（非 5 位）: {s}")
                continue
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

    def _v(x: Any) -> float | None:
        """NaN/None → None，否则转 float（对齐 amount 的 None 语义，避免 NaN 进 Parquet）。"""
        if x is None:
            return None
        try:
            f = float(x)
        except (TypeError, ValueError):
            return None
        return None if pd.isna(f) else f

    # DataFrame 列是 yahoo 格式（港股 4 位、.SH→.SS），需转换后取数；
    # 写库的 symbol 仍是规范格式（行内 sym），仅取数时用 yahoo 格式定位列
    for sym in symbols:
        yahoo_sym = to_yahoo_symbol(sym)
        try:
            sub = df.xs(yahoo_sym, level=1, axis=1) if is_multi else df
        except (KeyError, ValueError):
            continue
        for ts, r in sub.iterrows():
            close = _v(r.get("Close"))
            if close is None:  # 无 close 的分钟K 行无意义，跳过
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
                    "open": _v(r.get("Open")),
                    "high": _v(r.get("High")),
                    "low": _v(r.get("Low")),
                    "close": close,
                    "volume": _v(r.get("Volume")),
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

    # ③ 冷层：year/market/date 分区 + 文件内 (symbol,ts) 排序；幂等覆盖当日文件。
    # 分区日期用数据真实交易日（yfinance index 的首个交易日，交易所时区），
    # 不用入参 day——misfire 补跑跨 UTC 日界时 day 可能错位，数据日期才是准的。
    trade_date = _trade_date_of(rows) or day
    key = (
        f"minute_bars/year={trade_date.year}/market={market}/"
        f"date={trade_date.isoformat()}/part-000.parquet"
    )
    cs = get_cold_storage()
    try:
        await asyncio.to_thread(cs.write_parquet, key, accepted, sort_by=["symbol", "ts"])
    except Exception as e:  # noqa: BLE001 — 冷层写失败降级记日志，不连带阻塞其他市场
        logger.error(
            f"minute_kline {market} 写冷层失败（{len(accepted)} 行 → {key}）："
            f"{type(e).__name__}: {e}"
        )
        return 0
    logger.info(f"minute_kline {market} {trade_date}: {len(accepted)} rows → {key}")
    return len(accepted)


def _trade_date_of(rows: list[dict[str, Any]]) -> date | None:
    """从已落行的 ts（UTC epoch 秒）推导数据的真实交易日（取众数日的 UTC 日期）。

    分钟K 单行 ts 是 UTC；同一交易日内的行 UTC 日期一致（US/HK 盘后数据）。
    用于冷层分区 key，比信任入参 day 更抗 misfire 跨日界错位。
    """
    if not rows:
        return None
    days = [
        datetime.fromtimestamp(r["ts"], tz=timezone.utc).date()
        for r in rows
        if r.get("ts") is not None
    ]
    if not days:
        return None
    return max(set(days), key=days.count)


async def run_minute_kline_job(day: date | None = None) -> dict[str, int]:
    """每日分钟K 采集：US/HK 各市场采当日。返回各市场落冷层条数。"""
    logger.info("=== minute kline job start ===")
    day = day or datetime.now(timezone.utc).date()
    groups = _minute_symbols()
    counts: dict[str, int] = {}
    for market, symbols in groups.items():
        # 每市场独立降级：一个市场失败（拉取/质量/写冷层）不影响另一市场
        try:
            counts[market] = await fetch_and_store_minute_kline(market, symbols, day)
        except Exception:  # noqa: BLE001 — 双保险（fetch_and_store 内部已分层降级）
            logger.exception(f"minute_kline {market} 未捕获异常，跳过本市场")
            counts[market] = 0
    logger.info(
        "=== minute kline job done: "
        + ", ".join(f"{m}={c}" for m, c in counts.items())
        + " ==="
    )
    return counts
