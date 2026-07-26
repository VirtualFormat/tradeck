"""板块行情热度（概念/行业板块，直调 akshare，写入 board_heat）

说明：OpenBB REST API 只暴露标准模型，ConceptBoards 等自定义模型仅 Python SDK 可用，
因此本 job 在 backend 内直接调 akshare（上游同为东财，链路不变）。
"""
from __future__ import annotations

import logging
from typing import Any

from app.datasource import call_akshare
from app.db import get_pool

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


async def fetch_and_store_boards(board_type: str) -> int:
    """拉一类板块（concept/industry）行情，全量覆盖写入。返回写入条数。"""
    import akshare as ak

    def fetch():
        if board_type == "industry":
            return ak.stock_board_industry_name_em()
        return ak.stock_board_concept_name_em()

    try:
        df = await call_akshare(fetch)
    except Exception as e:
        logger.warning(f"akshare boards {board_type} failed: {e}")
        return 0
    if df is None or df.empty:
        logger.warning(f"No boards data for {board_type}")
        return 0

    rows = [
        (
            board_type,
            str(r.get("板块名称") or ""),
            str(r.get("板块代码") or "") or None,
            _f(r.get("涨跌幅")),
            _i(r.get("总市值")),
            _f(r.get("换手率")),
            str(r.get("领涨股票") or "") or None,
            _f(r.get("领涨股票-涨跌幅")),
        )
        for _, r in df.iterrows()
        if r.get("板块名称")
    ]
    if not rows:
        return 0

    pool = await get_pool()
    async with pool.acquire() as conn:
        # 只覆盖当天快照（保留历史日期，供回看）
        await conn.execute(
            "DELETE FROM board_heat WHERE board_type = $1 AND snapshot_date = CURRENT_DATE",
            board_type,
        )
        await conn.executemany(
            """
            INSERT INTO board_heat
                (board_type, name, code, change_percent, market_cap,
                 turnover_rate, leader_stock, leader_change, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW())
            """,
            rows,
        )
    logger.info(f"fetched {len(rows)} {board_type} boards")
    return len(rows)


async def run_board_heat_job() -> None:
    """定时任务：拉概念 + 行业板块行情热度"""
    logger.info("=== board heat job start ===")
    total = await fetch_and_store_boards("concept")
    total += await fetch_and_store_boards("industry")
    logger.info(f"=== board heat job done: {total} rows ===")
