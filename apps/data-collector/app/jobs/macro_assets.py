"""宏观资产（美元指数/离岸人民币/ETF）+ 美债收益率曲线

- macro_asset_prices：fx 走 /equity/price/historical 与 /currency/price/historical，
  etf 走 /etf/historical，均为 yfinance 源
- yield_curve_rates：/fixedincome/government/treasury_rates（federal_reserve 源，
  小数值 0.0443 = 4.43%，原样存库，API 层再 ×100 转 %）
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

from app.db import get_pool
from app.openbb_client import fetch_openbb

logger = logging.getLogger(__name__)


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except Exception:
        return None


# 跟踪的宏观资产：path 为 OpenBB 端点（fx 两类走不同端点）
MACRO_ASSETS = [
    {"symbol": "DX-Y.NYB", "name": "美元指数", "category": "fx", "path": "/equity/price/historical"},
    {"symbol": "USDCNH", "name": "离岸人民币", "category": "fx", "path": "/currency/price/historical"},
    {"symbol": "RSP", "name": "标普500等权", "category": "etf", "path": "/etf/historical"},
    {"symbol": "SPY", "name": "标普500", "category": "etf", "path": "/etf/historical"},
    {"symbol": "IWM", "name": "罗素2000", "category": "etf", "path": "/etf/historical"},
    {"symbol": "QQQ", "name": "纳指100", "category": "etf", "path": "/etf/historical"},
    {"symbol": "IVE", "name": "标普500价值", "category": "etf", "path": "/etf/historical"},
    {"symbol": "XLK", "name": "科技板块", "category": "etf", "path": "/etf/historical"},
    {"symbol": "XLP", "name": "必需消费", "category": "etf", "path": "/etf/historical"},
]

# 收益率曲线期限列（treasury_rates 返回字段名）
YIELD_TENORS = [
    "month_1", "month_3", "month_6",
    "year_1", "year_2", "year_3", "year_5",
    "year_7", "year_10", "year_20", "year_30",
]


async def fetch_and_store_macro_asset(symbol: str, name: str, category: str, path: str) -> int:
    """拉单个宏观资产近 400 天历史，UPSERT 写库。返回写入条数。"""
    end = date.today().isoformat()
    start = (date.today() - timedelta(days=400)).isoformat()

    data = await fetch_openbb(
        path,
        {
            "provider": "yfinance",
            "symbol": symbol,
            "start_date": start,
            "end_date": end,
        },
    )
    results = data.get("results", [])
    if not results:
        logger.warning(f"No macro asset data for {symbol}")
        return 0

    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = [
            (symbol, name, category, _parse_date(r.get("date")), r.get("close"))
            for r in results
            if r.get("close") is not None  # 跳过当日未收盘的 null close 行，防止覆盖有效值
        ]
        await conn.executemany(
            """
            INSERT INTO macro_asset_prices (symbol, name, category, date, close)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (symbol, date) DO UPDATE SET
                name = EXCLUDED.name, category = EXCLUDED.category,
                close = EXCLUDED.close, fetched_at = now()
            """,
            rows,
        )
    logger.info(f"fetched {len(results)} macro asset prices for {symbol}")
    return len(rows)


async def fetch_and_store_yield_curve() -> int:
    """拉美债收益率曲线近 400 天，宽行 UPSERT 进 yield_curve_rates。返回写入条数。"""
    end = date.today().isoformat()
    start = (date.today() - timedelta(days=400)).isoformat()

    data = await fetch_openbb(
        "/fixedincome/government/treasury_rates",
        {
            "provider": "federal_reserve",
            "start_date": start,
            "end_date": end,
        },
    )
    results = data.get("results", [])
    if not results:
        logger.warning("No treasury rates data")
        return 0

    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = [
            (
                _parse_date(r.get("date")),
                *(r.get(t) for t in YIELD_TENORS),
            )
            for r in results
            if _parse_date(r.get("date")) is not None
        ]
        await conn.executemany(
            """
            INSERT INTO yield_curve_rates
                (date, month_1, month_3, month_6, year_1, year_2, year_3,
                 year_5, year_7, year_10, year_20, year_30)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
            ON CONFLICT (date) DO UPDATE SET
                month_1 = EXCLUDED.month_1, month_3 = EXCLUDED.month_3,
                month_6 = EXCLUDED.month_6, year_1 = EXCLUDED.year_1,
                year_2 = EXCLUDED.year_2, year_3 = EXCLUDED.year_3,
                year_5 = EXCLUDED.year_5, year_7 = EXCLUDED.year_7,
                year_10 = EXCLUDED.year_10, year_20 = EXCLUDED.year_20,
                year_30 = EXCLUDED.year_30, fetched_at = now()
            """,
            rows,
        )
    logger.info(f"fetched {len(results)} treasury rates rows")
    return len(rows)


async def run_macro_assets_job() -> dict[str, int]:
    """定时任务：拉宏观资产历史 + 美债收益率曲线（每天一次）"""
    logger.info("=== macro assets job start ===")
    results = {asset["symbol"]: 0 for asset in MACRO_ASSETS}
    results["yield_curve"] = 0
    for asset in MACRO_ASSETS:
        try:
            results[asset["symbol"]] = await fetch_and_store_macro_asset(
                asset["symbol"], asset["name"], asset["category"], asset["path"]
            )
        except Exception as e:
            # 单资产失败跳过，job 正常结束
            logger.warning(f"macro asset {asset['symbol']} failed: {e}")
    try:
        results["yield_curve"] = await fetch_and_store_yield_curve()
    except Exception as e:
        logger.warning(f"yield curve fetch failed: {e}")
    total = sum(results.values())
    logger.info(f"=== macro assets job done: {total} rows ===")
    return results
