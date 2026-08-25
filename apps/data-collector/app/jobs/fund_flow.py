"""个股资金流向榜（findb stock_fund_flow 全市场主力净流入榜，写入 fund_flow）

数据源：findb /api/table?name=stock_fund_flow（A 股全市场，稳定），
按主力净流入（main_net）绝对额最大的一批（正/负各 Top N）写当天快照。
原 akshare 东财即时榜已退役：本地常被东财断连/封 IP，findb 为主数据源、
链路更稳，不再保留东财兜底（单一源语义更清晰）。

单位口径：findb pct_chg 与东财涨跌幅同为百分数；main_net（主力净流入）
为元，与东财即时榜净额口径一致，直接写入。
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

from app.datasource import findb_source
from app.db import get_pool
from app.jobs.board_map import _to_symbol
from app.quality import quality_gate

logger = logging.getLogger(__name__)

# 榜两端各取 Top N（主力净流入最大 + 净流出最大），合计至多 2N 行
_TOP_N = 500


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
    """定时任务：拉个股主力资金流向榜（每 5 分钟）"""
    logger.info("=== fund flow job start ===")

    # 净流入 Top N（主力净流入降序）
    data = await findb_source.fetch_table(
        "stock_fund_flow", sort="main_net", order="desc", limit=_TOP_N
    )
    if not data:
        logger.warning("findb stock_fund_flow 为空，保留旧快照")
        return 0

    # 净流出 Top N（升序取尾部），去重合并，保证榜两端都有数据
    bottom = await findb_source.fetch_table(
        "stock_fund_flow", sort="main_net", order="asc", limit=_TOP_N
    )
    if bottom:
        seen = {str(r.get("code") or "") for r in data}
        data += [r for r in bottom if str(r.get("code") or "") not in seen]

    rows = []
    for r in data:
        sym = _to_symbol(str(r.get("code") or ""))
        if not sym:
            continue
        rows.append((
            sym,
            str(r.get("name") or "") or None,
            _f(r.get("price")),
            _f(r.get("pct_chg")),
            None,  # turnover_rate：findb 无此字段，置空
            None,  # amount_in：findb 只给主力净额，无流入/流出拆分
            None,  # amount_out：同上
            _i(r.get("main_net")),
            _i(r.get("amount_total")),
        ))
    if not rows:
        return 0

    # 有效净额行数过少视为源异常（保留最近交易日快照，不覆盖）
    valid_count = sum(1 for r in rows if r[7] is not None)
    if valid_count < 100:
        logger.warning(
            f"fund flow 有效净额仅 {valid_count} 行（findb 数据异常），保留旧快照"
        )
        return 0

    # 写库前把 tuple 转 dict 过质量闸（键与 fund_flow 列名一致；snapshot_date 恒为当天，
    # 与 INSERT 的 DEFAULT CURRENT_DATE 同口径），被拦的行不进 INSERT
    _cols = (
        "symbol", "name", "price", "change_percent", "turnover_rate",
        "amount_in", "amount_out", "net_amount", "amount_total",
    )
    today = date.today()
    dict_rows = [
        {**dict(zip(_cols, row)), "snapshot_date": today} for row in rows
    ]
    accepted = await quality_gate("fund_flow", dict_rows)
    if not accepted:
        logger.warning("fund flow 全部被质量闸拦截，保留旧快照")
        return 0
    rows = [tuple(d[c] for c in _cols) for d in accepted]

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
