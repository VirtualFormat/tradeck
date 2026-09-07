"""温层数据源：从 data pool 冷层 Parquet 读取分钟K 并换算为 CH 契约（UTC ts）。

data pool 分钟分区的 ``datetime`` 列是**交易所本地 naive 时间**
（CN=Asia/Shanghai、HK=Asia/Hong_Kong、US=America/New_York，见
minute_kline._normalize_rows / minute_storage._normalize_delta_rows），
而 ``tradeck.minute_bars`` 表的 ``ts`` 纪律是**统一 UTC**。

本模块是冷层（本地时间）→ 温层（UTC）之间唯一的换算边界：
读 delta 分区（DuckDB）后按市场时区把 ``datetime`` 转为 UTC 的
``YYYY-MM-DD HH:MM:SS`` 字符串，供 ``minute_bars.replace_market_day`` 直写。

只读，不写冷层。DuckDB 为 CPU/IO 操作，调用方用 asyncio.to_thread 包裹。
"""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

# 市场 → 交易所本地时区（与 minute_kline._normalize_rows 的映射保持一致）
_MARKET_ZONE = {
    "CN": "Asia/Shanghai",
    "HK": "Asia/Hong_Kong",
    "US": "America/New_York",
}


def _sql_literal(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def read_delta_day_as_utc(path: Path, market: str, day: date) -> list[dict[str, Any]]:
    """读一个 minute_delta 日分区，返回 CH 契约行（ts 已换算为 UTC）。

    返回列：symbol/market/ts(UTC 字符串)/open/high/low/close/volume/amount，
    与 warm_storage.minute_bars.serialize_rows 的输入契约对齐。
    文件不存在返回空列表（调用方据此跳过）。失败抛异常（由调用方 catch 降级）。
    """
    if not path.exists():
        return []
    if market not in _MARKET_ZONE:
        raise ValueError(f"未知市场 {market!r}，无法换算时区")

    import duckdb

    connection = duckdb.connect()
    try:
        raw = connection.execute(
            "SELECT symbol, datetime, open, high, low, close, volume, amount "
            f"FROM read_parquet({_sql_literal(path)}, hive_partitioning=false) "
            "ORDER BY symbol, datetime",
        ).fetchall()
    finally:
        connection.close()

    zone = ZoneInfo(_MARKET_ZONE[market])
    rows: list[dict[str, Any]] = []
    for symbol, local_dt, o, h, low, c, vol, amt in raw:
        if local_dt is None or symbol is None:
            continue
        # naive 本地时间 → 赋予交易所时区 → 转 UTC → 去 tzinfo 格式化
        utc_dt = local_dt.replace(tzinfo=zone).astimezone(ZoneInfo("UTC"))
        rows.append(
            {
                "symbol": str(symbol),
                "market": market,
                "ts": utc_dt.strftime("%Y-%m-%d %H:%M:%S"),
                "open": o,
                "high": h,
                "low": low,
                "close": c,
                "volume": vol,
                "amount": amt,
            }
        )
    return rows
