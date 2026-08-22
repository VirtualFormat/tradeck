"""指数历史（调 OpenBB index/historical，写入 index_prices）"""
from __future__ import annotations

import logging
from datetime import date, timedelta

from app.db import get_pool
from app.openbb_client import fetch_openbb
from app.quality import quality_gate

logger = logging.getLogger(__name__)


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except Exception:
        return None


# 跟踪的指数
TRACKED_INDICES = [
    {"symbol": "^GSPC", "market": "US"},
    {"symbol": "^IXIC", "market": "US"},
    {"symbol": "^DJI", "market": "US"},
    {"symbol": "^HSI", "market": "HK"},
    {"symbol": "^HSCEI", "market": "HK"},
    {"symbol": "000001.SS", "market": "CN"},
    {"symbol": "399001.SZ", "market": "CN"},
    {"symbol": "399006.SZ", "market": "CN"},
    {"symbol": "^N225", "market": "JP"},  # 日经 225
    {"symbol": "^STOXX50E", "market": "EU"},  # 欧洲斯托克 50
    {"symbol": "^VIX", "market": "VOL"},  # 恐慌指数
]

# 大宗商品（用 index/historical 拉）
TRACKED_COMMODITIES = [
    {"symbol": "GC=F", "market": "US"},  # 黄金
    {"symbol": "CL=F", "market": "US"},  # 原油
    {"symbol": "SI=F", "market": "US"},  # 白银
    {"symbol": "BTC-USD", "market": "US"},  # 比特币
    {"symbol": "HG=F", "market": "US"},  # 铜
]


async def fetch_and_store_index(symbol: str, market: str) -> int:
    """拉单只指数历史，写入 DB。返回写入条数。"""
    # yfinance 的 end_date 为开区间，传明天才能包含刚收盘的当日 K 线。
    end = (date.today() + timedelta(days=1)).isoformat()
    start = (date.today() - timedelta(days=365)).isoformat()

    data = await fetch_openbb(
        "/index/price/historical",
        {
            "provider": "yfinance",
            "symbol": symbol,
            "start_date": start,
            "end_date": end,
        },
    )
    results = data.get("results", [])
    if not results:
        logger.warning(f"No index data for {symbol}")
        return 0

    # 写库前组装 dict 行过质量闸，被拦的行不进 UPSERT
    dict_rows = [
        {
            "symbol": symbol,
            "market": market,
            "date": _parse_date(r.get("date")),
            "close": r.get("close"),
            "volume": r.get("volume"),
        }
        for r in results
        if r.get("close") is not None  # 跳过当日未收盘的 null close 行，防止覆盖有效值
    ]
    accepted = await quality_gate("index_prices", dict_rows)
    if not accepted:
        return 0

    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = [
            (d["symbol"], d["market"], d["date"], d["close"], d["volume"])
            for d in accepted
        ]
        await conn.executemany(
            """
            INSERT INTO index_prices (symbol, market, date, close, volume)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (symbol, date) DO UPDATE SET
                close = EXCLUDED.close, volume = EXCLUDED.volume
            """,
            rows,
        )
    logger.info(f"fetched {len(accepted)} index prices for {symbol}")
    return len(accepted)


async def run_indices_job(
    markets: tuple[str, ...] | None = None,
) -> dict[str, int]:
    """定时任务：按市场拉指数历史；markets=None 时全量执行。"""
    targets = [
        item
        for item in TRACKED_INDICES + TRACKED_COMMODITIES
        if markets is None or item["market"] in markets
    ]
    market_label = ",".join(markets) if markets else "ALL"
    logger.info(f"=== indices job start (markets={market_label}) ===")
    results: dict[str, int] = {}
    for idx in targets:
        count = await fetch_and_store_index(idx["symbol"], idx["market"])
        results[f"{idx['market']}:{idx['symbol']}"] = count
    total = sum(results.values())
    logger.info(f"=== indices job done (markets={market_label}): {total} rows ===")
    return results
