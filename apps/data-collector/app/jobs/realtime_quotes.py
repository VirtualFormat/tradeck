"""盘中轮询报价（A 股经 call_akshare 批量直调，港美股走 yfinance，写入 quote_snapshots）"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, time, timezone
from typing import Any
from zoneinfo import ZoneInfo

from app.datasource import call_akshare, fetch_openbb
from app.db import get_pool
from app.constants import TRACKED_SYMBOLS
from app.markets import pick_market, pick_provider, to_yahoo_symbol

logger = logging.getLogger(__name__)

_QUOTE_TIME_FIELDS = (
    "date",
    "last_price_time",
    "regular_market_time",
    "regularMarketTime",
    "updated_at",
    "timestamp",
)
_DATE_ONLY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MARKET_TIME_ZONES = {
    "CN": ZoneInfo("Asia/Shanghai"),
    "HK": ZoneInfo("Asia/Hong_Kong"),
    "US": ZoneInfo("America/New_York"),
}
_MARKET_CLOSE_TIMES = {
    "CN": time(15, 0),
    "HK": time(16, 0),
    "US": time(16, 0),
}


def _f(v: Any) -> float | None:
    try:
        f = float(v) if v is not None else None
    except (TypeError, ValueError):
        return None
    # pandas NaN 不等于自身
    return None if f is not None and f != f else f


def _i(v: Any) -> int | None:
    try:
        return int(float(v)) if v is not None else None
    except (TypeError, ValueError):
        return None


def _market_close(value: date, market: str) -> datetime:
    """将仅含交易日的 provider 值映射到市场本地常规收盘时刻。"""
    zone = _MARKET_TIME_ZONES.get(market, timezone.utc)
    close_time = _MARKET_CLOSE_TIMES.get(market, time(0, 0))
    return datetime.combine(value, close_time, tzinfo=zone).astimezone(timezone.utc)


def _parse_quote_time(value: Any, market: str) -> tuple[datetime | None, bool]:
    """解析 provider 时间，返回 (UTC 时间, 是否仅含日期)。"""
    if value is None or isinstance(value, bool):
        return None, False

    if isinstance(value, datetime):
        parsed = value
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=_MARKET_TIME_ZONES.get(market, timezone.utc))
        return parsed.astimezone(timezone.utc), False

    if isinstance(value, date):
        return _market_close(value, market), True

    if isinstance(value, (int, float)):
        numeric = float(value)
        if numeric != numeric or numeric <= 0:
            return None, False
        # 同时兼容 Unix 秒和毫秒时间戳。
        if numeric >= 100_000_000_000:
            numeric /= 1000
        try:
            return datetime.fromtimestamp(numeric, tz=timezone.utc), False
        except (OverflowError, OSError, ValueError):
            return None, False

    if not isinstance(value, str):
        return None, False

    text = value.strip()
    if not text:
        return None, False
    if _DATE_ONLY_RE.fullmatch(text):
        try:
            return _market_close(date.fromisoformat(text), market), True
        except ValueError:
            return None, False
    try:
        numeric = float(text)
    except ValueError:
        numeric = None
    if numeric is not None:
        return _parse_quote_time(numeric, market)

    normalized = text[:-1] + "+00:00" if text.endswith(("Z", "z")) else text
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None, False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_MARKET_TIME_ZONES.get(market, timezone.utc))
    return parsed.astimezone(timezone.utc), False


def _extract_data_as_of(quote: dict[str, Any], market: str) -> datetime | None:
    """从 provider 报价中提取真实行情时间；无法证明时返回 None。"""
    date_only_fallback: datetime | None = None
    for field in _QUOTE_TIME_FIELDS:
        parsed, is_date_only = _parse_quote_time(quote.get(field), market)
        if parsed is None:
            continue
        if is_date_only:
            date_only_fallback = date_only_fallback or parsed
            continue
        return parsed
    return date_only_fallback


async def _fetch_akshare_quotes(symbols: list[str]) -> list[dict]:
    """一次拉 A 股全市场 spot，本地过滤 tracked，映射到标准报价 dict。

    change_percent 存小数（0.0715 = 7.15%），与 seed/movers 口径一致。
    失败/空返回 []（降级，不抛）。
    """
    # tracked 6 位代码 → 内部 symbol（600519 → 600519.SH）
    code_map = {s.split(".")[0]: s for s in symbols}

    def fetch():
        import akshare as ak

        return ak.stock_zh_a_spot_em()

    try:
        df = await call_akshare(fetch)
    except Exception as e:
        logger.warning(f"akshare spot quotes failed: {e}")
        return []
    if df is None or df.empty:
        return []

    quotes: list[dict] = []
    for _, r in df.iterrows():
        sym = code_map.get(str(r.get("代码") or "").strip())
        if not sym:
            continue
        pct = _f(r.get("涨跌幅"))  # spot_em 返回百分数（7.15），转小数
        quotes.append({
            "symbol": sym,
            "name": str(r.get("名称") or "") or None,
            "last_price": _f(r.get("最新价")),
            "change": _f(r.get("涨跌额")),
            "change_percent": pct / 100 if pct is not None else None,
            "volume": _i(r.get("成交量")),
        })
    return quotes


async def fetch_and_store_quotes_by_market(symbols: list[str]) -> dict[str, int]:
    """批量拉报价并写库，返回各市场实际写入条数。"""
    # 按 provider 分组
    akshare_syms = [s for s in symbols if pick_provider(s) == "akshare"]
    yfinance_syms = [s for s in symbols if pick_provider(s) == "yfinance"]

    all_quotes: list[dict] = []

    if akshare_syms:
        all_quotes.extend(await _fetch_akshare_quotes(akshare_syms))

    if yfinance_syms:
        # 出向映射：yfinance 用 Yahoo 格式（.SH→.SS、港股 5→4 位），
        # 响应 symbol 映射回规范格式再写库
        yahoo_to_canonical = {to_yahoo_symbol(s): s for s in yfinance_syms}
        data = await fetch_openbb(
            "/equity/price/quote",
            {"provider": "yfinance", "symbol": ",".join(yahoo_to_canonical)},
        )
        for q in data.get("results", []):
            resp_sym = q.get("symbol")
            if resp_sym in yahoo_to_canonical:
                q["symbol"] = yahoo_to_canonical[resp_sym]
            # yfinance quote 不返回 change/change_percent，用 prev_close 现算
            # （change_percent 存小数，与 akshare 分支口径一致）
            last, prev = _f(q.get("last_price")), _f(q.get("prev_close"))
            if last is not None and prev:
                if q.get("change") is None:
                    q["change"] = round(last - prev, 4)
                if q.get("change_percent") is None:
                    q["change_percent"] = (last - prev) / prev
            all_quotes.append(q)

    if not all_quotes:
        logger.warning("No quotes fetched")
        return {}

    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = [
            (
                q.get("symbol"),
                q.get("name"),
                q.get("last_price"),
                q.get("change"),
                q.get("change_percent"),
                q.get("volume"),
                pick_market(q.get("symbol", "")),
                _extract_data_as_of(q, pick_market(q.get("symbol", ""))),
            )
            for q in all_quotes
            if q.get("symbol")
        ]
        await conn.executemany(
            """
            INSERT INTO quote_snapshots
                (symbol, name, last_price, change, change_percent, volume,
                 market, data_as_of, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW())
            ON CONFLICT (symbol) DO UPDATE SET
                name = EXCLUDED.name,
                last_price = EXCLUDED.last_price,
                -- 缺涨跌时保留已有值（兜底；yfinance 正常已由 prev_close 现算）
                change = COALESCE(EXCLUDED.change, quote_snapshots.change),
                change_percent = COALESCE(EXCLUDED.change_percent, quote_snapshots.change_percent),
                volume = EXCLUDED.volume,
                market = EXCLUDED.market,
                data_as_of = EXCLUDED.data_as_of,
                updated_at = NOW()
            """,
            rows,
        )
    counts: dict[str, int] = {}
    for row in rows:
        market = row[6]
        counts[market] = counts.get(market, 0) + 1
    logger.info(
        "quotes stored: "
        + ", ".join(
            f"{market}={counts.get(market, 0)}" for market in ("CN", "HK", "US")
        )
    )
    return counts


async def fetch_and_store_quotes(symbols: list[str]) -> int:
    """兼容按需回源调用：批量拉报价并返回总写入条数。"""
    counts = await fetch_and_store_quotes_by_market(symbols)
    return sum(counts.values())


async def run_realtime_quotes_job() -> dict[str, int]:
    """定时任务：轮询所有跟踪股票报价"""
    logger.info("=== realtime quotes job start ===")
    counts = await fetch_and_store_quotes_by_market(TRACKED_SYMBOLS)
    logger.info(
        "=== realtime quotes job done: "
        + ", ".join(
            f"{market}={counts.get(market, 0)}" for market in ("CN", "HK", "US")
        )
        + " ==="
    )
    return {market: counts.get(market, 0) for market in ("CN", "HK", "US")}
