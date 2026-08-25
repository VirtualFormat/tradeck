"""复权因子同步 job：findb adj_factor 表 → PG adjust_factors。

链路：findb /api/table?name=adj_factor（单 code 逐标的，order=desc 取最近
      ~250 个交易日，覆盖日K 全量初始化窗口）→ UPSERT adjust_factors。

findb code 映射复用 minute_kline 的 _to_findb_code：美股裸码加 .US
（AAPL→AAPL.US），A股/港股与规范一致（600036.SH/00700.HK）。

纪律：单一写者（仅 collector 写本表）、UPSERT 幂等（PK symbol+date 覆盖）、
优雅降级（FINDB_KEY 未配置或 findb 失败记日志返回空，不抛错；
单标的失败只影响该标的，不拖累其余）。
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

from app.config import settings
from app.constants import TRACKED_SYMBOLS
from app.db import get_pool
from app.markets import pick_market

logger = logging.getLogger(__name__)

# 每标的拉取的最近交易日数：覆盖日K 全量初始化窗口（~250 个交易日）
_FACTOR_LIMIT = 250

_UPSERT_SQL = """
    INSERT INTO adjust_factors (symbol, date, qfq, hfq, fetched_at)
    VALUES ($1, $2, $3, $4, NOW())
    ON CONFLICT (symbol, date) DO UPDATE SET
        qfq = EXCLUDED.qfq,
        hfq = EXCLUDED.hfq,
        fetched_at = NOW()
"""


def _to_float(x: Any) -> float | None:
    """NaN/None/非法值 → None，否则转 float（因子列允许 NULL）。"""
    if x is None:
        return None
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return None if f != f else f


def _parse_factor_date(value: Any) -> date | None:
    """findb date 形如 2026-07-10T00:00:00 → date 对象（asyncpg 不接受字符串）。"""
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


async def _fetch_symbol_factors(code: str) -> list[dict]:
    """拉单标的复权因子（findb adj_factor 为单 code 接口，order=desc 取最近 N 条）。"""
    from app.datasource import findb_source

    return await findb_source.fetch_table(
        "adj_factor", col="code", val=code, order="desc", limit=_FACTOR_LIMIT
    )


async def _fetch_and_store_symbol(symbol: str, market: str) -> int:
    """拉单标的因子并 UPSERT 写库，返回写入条数。失败优雅降级返回 0。"""
    # 延迟 import 避免模块层循环依赖（minute_kline 属同一 jobs 包）
    from app.jobs.minute_kline import _to_findb_code

    code = _to_findb_code(symbol, market)
    rows = await _fetch_symbol_factors(code)
    if not rows:
        return 0

    # 解析为 (symbol, date, qfq, hfq) 元组，跳过日期非法的行
    records = []
    for r in rows:
        d = _parse_factor_date(r.get("date"))
        if d is None:
            continue
        records.append((symbol, d, _to_float(r.get("qfq")), _to_float(r.get("hfq"))))
    if not records:
        return 0

    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.executemany(_UPSERT_SQL, records)
    return len(records)


async def run_adjust_factors_job() -> int:
    """job 入口：遍历 tracked 标的逐只同步复权因子，返回总写入条数。"""
    logger.info("=== adjust factors job start ===")

    # findb 未配置密钥时整体降级（各标的 fetch 也只会返回空，提前短路省 100 次调用）
    if not settings.FINDB_KEY:
        logger.warning(
            "=== adjust factors job done: 0 rows（未配置 FINDB_KEY，跳过）==="
        )
        return 0

    total = 0
    failed = 0
    for symbol in TRACKED_SYMBOLS:
        try:
            total += await _fetch_and_store_symbol(symbol, pick_market(symbol))
        except Exception:  # noqa: BLE001 — 单标的失败降级：记日志跳过，不影响其他标的
            failed += 1
            logger.warning(f"adjust factors 拉取失败，跳过标的 {symbol}", exc_info=True)

    logger.info(
        "=== adjust factors job done: %d rows%s ===",
        total,
        f"（{failed} 只标的失败跳过）" if failed else "",
    )
    return total
