"""个股资金流向榜（东财即时榜，直调 akshare，写入 fund_flow）

一次调用返回全市场排行（按主力净额排序），非交易时段/封 IP 返回空时
不写库，保留最后有效快照。
"""
from __future__ import annotations

import logging
from typing import Any

from app.datasource import call_akshare
from app.db import get_pool
from app.jobs.board_map import _to_symbol

logger = logging.getLogger(__name__)


def _f(v: Any) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _i(v: Any) -> int | None:
    try:
        return int(float(v)) if v is not None else None
    except (TypeError, ValueError):
        return None


async def run_fund_flow_job() -> int:
    """定时任务：拉个股主力资金流向即时榜（每 5 分钟）"""
    logger.info("=== fund flow job start ===")
    import akshare as ak

    def fetch():
        return ak.stock_fund_flow_individual(symbol="即时")

    try:
        df = await call_akshare(fetch)
    except Exception as e:
        logger.warning(f"akshare fund flow failed: {e}")
        return 0
    if df is None or df.empty:
        logger.warning("fund flow 为空（非交易时段或接口受限），保留旧快照")
        return 0

    rows = []
    for _, r in df.iterrows():
        sym = _to_symbol(str(r.get("股票代码") or ""))
        if not sym:
            continue
        rows.append((
            sym,
            str(r.get("股票简称") or "") or None,
            _f(r.get("最新价")),
            _f(r.get("涨跌幅")),
            _f(r.get("换手率")),
            _i(r.get("流入资金")),
            _i(r.get("流出资金")),
            _i(r.get("净额")),
            _i(r.get("成交额")),
        ))
    if not rows:
        return 0

    # 非交易时段东财只返回个位数有效净额——此时不写库，保留最近交易日快照
    valid_count = sum(1 for r in rows if r[7] is not None)
    if valid_count < 100:
        logger.warning(
            f"fund flow 有效净额仅 {valid_count} 行（非交易时段），保留旧快照"
        )
        return 0

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            # 只覆盖当天快照（保留历史日期，供回看）
            await conn.execute(
                "DELETE FROM fund_flow WHERE snapshot_date = CURRENT_DATE"
            )
            await conn.executemany(
                """
                INSERT INTO fund_flow
                    (symbol, name, price, change_percent, turnover_rate,
                     amount_in, amount_out, net_amount, amount_total, updated_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, NOW())
                """,
                rows,
            )
    logger.info(f"=== fund flow job done: {len(rows)} rows ===")
    return len(rows)
