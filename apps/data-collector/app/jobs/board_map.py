"""股票 ↔ 板块归属映射（东财成分股接口反解，写入 symbol_board_map）

拉取范围：board_heat 中的全部行业板块 + 概念板块市值 Top 150（控制拉取量）。
成分低频变化，job 每周刷新一次，全量覆盖重建。
"""
from __future__ import annotations

import logging

from app.datasource import call_akshare
from app.db import get_pool

logger = logging.getLogger(__name__)

CONCEPT_LIMIT = 150  # 概念板块只拉市值 Top N


def _to_symbol(code: str) -> str | None:
    """6 位代码 → tradeck symbol 格式"""
    code = code.strip()
    if len(code) != 6 or not code.isdigit():
        return None
    if code.startswith("6"):
        return f"{code}.SS"
    if code.startswith(("0", "3")):
        return f"{code}.SZ"
    if code.startswith(("4", "8")):
        return f"{code}.BJ"
    return None


async def _fetch_cons(board_type: str, board_name: str) -> list[str]:
    """拉单板块成分股代码列表。"""
    import akshare as ak

    def fetch():
        if board_type == "industry":
            return ak.stock_board_industry_cons_em(symbol=board_name)
        return ak.stock_board_concept_cons_em(symbol=board_name)

    try:
        df = await call_akshare(fetch)
    except Exception as e:
        logger.warning(f"akshare board cons failed for {board_name}: {e}")
        return []
    if df is None or df.empty:
        return []
    symbols = []
    for _, r in df.iterrows():
        sym = _to_symbol(str(r.get("代码") or ""))
        if sym:
            symbols.append(sym)
    return symbols


async def run_board_map_job() -> int:
    """定时任务：重建 symbol_board_map 映射"""
    logger.info("=== board map job start ===")
    pool = await get_pool()

    # 拉取范围：全部行业板块 + 概念板块市值 Top N
    async with pool.acquire() as conn:
        boards = await conn.fetch(
            """
            (SELECT board_type, name, code FROM board_heat WHERE board_type = 'industry')
            UNION ALL
            (SELECT board_type, name, code FROM board_heat
             WHERE board_type = 'concept'
             ORDER BY market_cap DESC NULLS LAST LIMIT $1)
            """,
            CONCEPT_LIMIT,
        )
    if not boards:
        logger.warning("board_heat 为空，跳过 board map job")
        return 0

    # 逐板块拉成分股，组装映射行
    map_rows: list[tuple[str, str, str, str | None]] = []
    for b in boards:
        symbols = await _fetch_cons(b["board_type"], b["name"])
        map_rows.extend(
            (sym, b["board_type"], b["name"], b["code"]) for sym in symbols
        )

    if not map_rows:
        logger.warning("=== board map job done: 0 rows（akshare 全部失败） ===")
        return 0

    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("DELETE FROM symbol_board_map")
            await conn.executemany(
                """
                INSERT INTO symbol_board_map (symbol, board_type, board_name, board_code)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (symbol, board_type, board_name) DO NOTHING
                """,
                map_rows,
            )
    logger.info(f"=== board map job done: {len(map_rows)} rows ===")
    return len(map_rows)
