"""股票 ↔ 板块归属映射：同花顺成分股主源，akshare 兜底。"""
from __future__ import annotations

import logging

from app.datasource import call_akshare, hithink_source
from app.db import get_pool

logger = logging.getLogger(__name__)

def _to_symbol(code: str) -> str | None:
    code = code.strip()
    if len(code) != 6 or not code.isdigit():
        return None
    if code.startswith("6"):
        return f"{code}.SH"
    if code.startswith(("0", "3")):
        return f"{code}.SZ"
    if code.startswith(("4", "8", "9")):
        return f"{code}.BJ"
    return None


async def _fetch_akshare_cons(board_type: str, board_name: str) -> list[str]:
    import akshare as ak

    def fetch():
        if board_type == "industry":
            return ak.stock_board_industry_cons_em(symbol=board_name)
        return ak.stock_board_concept_cons_em(symbol=board_name)

    try:
        frame = await call_akshare(fetch)
    except Exception as exc:  # noqa: BLE001
        logger.warning("akshare board cons failed for %s: %s", board_name, exc)
        return []
    if frame is None or frame.empty:
        return []
    return [
        symbol
        for _, row in frame.iterrows()
        if (symbol := _to_symbol(str(row.get("代码") or "")))
    ]


async def _fetch_cons(
    board_type: str,
    board_name: str,
    board_code: str | None,
) -> list[str]:
    if board_code:
        items = await hithink_source.get_index_constituents(board_code)
        symbols = [
            str(item.get("thscode") or "").strip().upper()
            for item in items
            if item.get("thscode")
        ]
        if symbols:
            return symbols
    logger.warning("hithink board cons empty for %s, fallback akshare", board_name)
    return await _fetch_akshare_cons(board_type, board_name)


async def run_board_map_job() -> int:
    logger.info("=== board map job start ===")
    pool = await get_pool()
    async with pool.acquire() as connection:
        boards = await connection.fetch(
            """
            SELECT DISTINCT ON (board_type, code)
                   board_type, name, code
            FROM board_heat
            WHERE code IS NOT NULL
            ORDER BY board_type, code, snapshot_date DESC
            """
        )
    if not boards:
        return 0

    # 代码体系过滤（2026-09-09 修复板块舆情为空）：board_heat 混两套代码——
    # 同花顺指数（881/884/885/886.TI 等 .TI 结尾）与申万/东财行业代码
    # （801/850/859.SI 等 .SI 结尾）。同花顺成分接口只认 .TI（.SI 报
    # "Unknown thscode"）。原逻辑把全部板块都拿去问同花顺，.SI 必然为空，
    # 把覆盖率拉低到 <80%（实测 .TI 仅 59%），触发「保留旧映射」——导致
    # symbol_board_map 永远停在残缺残留，板块舆情聚合（board_sentiment）空。
    # 修复：只对 .TI 板块取成分，覆盖率分母改为 .TI 板块数；
    # .SI 板块跳过（它们的成分需东财/申万源，当前 akshare 被封，见 backlog）。
    ti_boards = [b for b in boards if str(b["code"] or "").endswith(".TI")]
    skipped = len(boards) - len(ti_boards)
    if skipped:
        logger.info(
            "board map: 跳过 %d 个非同花顺代码板块（.SI 申万/东财，同花顺成分接口不认）",
            skipped,
        )
    boards = ti_boards
    if not boards:
        logger.warning("=== board map job done: 0 rows（无 .TI 板块） ===")
        return 0

    mapped: list[tuple[str, str, str, str | None]] = []
    boards_with_data = 0
    for board in boards:
        symbols = await _fetch_cons(
            board["board_type"], board["name"], board["code"]
        )
        mapped.extend(
            (symbol, board["board_type"], board["name"], board["code"])
            for symbol in symbols
        )
        if symbols:
            boards_with_data += 1
    if not mapped:
        logger.warning("=== board map job done: 0 rows ===")
        return 0
    if boards_with_data < int(len(boards) * 0.8):
        logger.warning(
            "board map 覆盖不足: %d/%d 板块有成分，保留旧映射",
            boards_with_data,
            len(boards),
        )
        return 0

    async with pool.acquire() as connection:
        async with connection.transaction():
            await connection.execute("DELETE FROM symbol_board_map")
            await connection.executemany(
                """
                INSERT INTO symbol_board_map
                    (symbol, board_type, board_name, board_code)
                VALUES ($1,$2,$3,$4)
                ON CONFLICT (symbol, board_type, board_name) DO NOTHING
                """,
                mapped,
            )
    logger.info("=== board map job done: %d rows ===", len(mapped))
    return len(mapped)
