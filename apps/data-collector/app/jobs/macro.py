"""宏观数据（调 OpenBB oecd/federal_reserve，写入 macro_indicators）"""
from __future__ import annotations

import logging
from datetime import date

from app.db import get_pool
from app.openbb_client import fetch_openbb
from app.quality import quality_gate

logger = logging.getLogger(__name__)


async def fetch_and_store_macro(name: str, path: str, params: dict, value_field: str = "value") -> int:
    """拉宏观指标，写入 DB。返回写入条数。"""
    data = await fetch_openbb(path, params)
    results = data.get("results", [])
    if not results:
        logger.warning(f"No macro data for {name}")
        return 0

    # 先解析出有效行并组装 dict 过质量闸（键与 macro_indicators 列名一致）
    dict_rows = []
    for r in results:
        d = r.get("date")
        v = r.get(value_field)
        if not d or v is None:
            continue
        try:
            d_obj = date.fromisoformat(str(d)[:10])
        except Exception:
            continue
        dict_rows.append({"name": name, "date": d_obj, "value": float(v)})

    accepted = await quality_gate("macro_indicators", dict_rows)
    if not accepted:
        return 0

    pool = await get_pool()
    async with pool.acquire() as conn:
        for row in accepted:
            await conn.execute(
                """
                INSERT INTO macro_indicators (name, date, value)
                VALUES ($1, $2, $3)
                ON CONFLICT (name, date) DO UPDATE SET value = EXCLUDED.value
                """,
                row["name"],
                row["date"],
                row["value"],
            )
    logger.info(f"fetched {len(accepted)} {name} data points")
    return len(accepted)


async def run_macro_job() -> dict[str, int]:
    """定时任务：拉所有宏观数据"""
    logger.info("=== macro job start ===")
    counts: dict[str, int] = {}

    # CPI
    counts["CPI"] = await fetch_and_store_macro(
        "CPI", "/economy/cpi", {"provider": "oecd", "limit": 12}
    )
    # 失业率
    counts["Unemployment"] = await fetch_and_store_macro(
        "Unemployment", "/economy/unemployment", {"provider": "oecd", "limit": 12}
    )
    # GDP
    counts["GDP_Nominal"] = await fetch_and_store_macro(
        "GDP_Nominal", "/economy/gdp/nominal", {"provider": "oecd", "limit": 20}
    )
    # EFFR
    counts["EFFR"] = await fetch_and_store_macro(
        "EFFR", "/fixedincome/rate/effr", {"provider": "federal_reserve", "limit": 12},
        value_field="rate",
    )
    # SOFR
    counts["SOFR"] = await fetch_and_store_macro(
        "SOFR", "/fixedincome/rate/sofr", {"provider": "federal_reserve", "limit": 12},
        value_field="rate",
    )

    total = sum(counts.values())
    logger.info(f"=== macro job done: {total} data points ===")
    return counts
