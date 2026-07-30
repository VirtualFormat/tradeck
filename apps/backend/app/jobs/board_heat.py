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
        f = float(v) if v is not None else None
    except (TypeError, ValueError):
        return None
    return None if f is not None and f != f else f


def _i(v: Any) -> int | None:
    try:
        f = float(v) if v is not None else None
    except (TypeError, ValueError):
        return None
    return None if f is None or f != f else int(f)


async def _fetch_ths_industry_rows() -> list[tuple]:
    """同花顺行业行情兜底。

    东财行业接口被断连时，使用同花顺行业一览表。该源没有总市值，
    因此将总成交额（亿元→元）作为 Treemap 面积权重，并用 THS: 前缀
    标记 code，API 据此返回正确的数据源与面积口径。
    """
    import akshare as ak

    try:
        summary = await call_akshare(ak.stock_board_industry_summary_ths)
        names = await call_akshare(ak.stock_board_industry_name_ths)
    except Exception as e:
        logger.warning(f"akshare boards industry THS fallback failed: {e}")
        return []
    if summary is None or summary.empty:
        return []

    code_map: dict[str, str] = {}
    if names is not None and not names.empty:
        code_map = {
            str(r.get("name") or "").strip(): str(r.get("code") or "").strip()
            for _, r in names.iterrows()
            if r.get("name")
        }

    rows = []
    for _, r in summary.iterrows():
        name = str(r.get("板块") or "").strip()
        if not name:
            continue
        amount_100m = _f(r.get("总成交额"))
        rows.append(
            (
                "industry",
                name,
                f"THS:{code_map.get(name, '')}",
                _f(r.get("涨跌幅")),
                int(amount_100m * 1e8) if amount_100m is not None else None,
                None,
                str(r.get("领涨股") or "").strip() or None,
                _f(r.get("领涨股-涨跌幅")),
            )
        )
    logger.info(f"ths industry fallback: {len(rows)} boards")
    return rows


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
        df = None

    if df is not None and not df.empty:
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
    elif board_type == "industry":
        rows = await _fetch_ths_industry_rows()
    else:
        rows = []

    if not rows:
        logger.warning(f"No boards data for {board_type}")
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
