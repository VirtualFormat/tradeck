"""板块行情热度（findb 同花顺概念指数 + 申万行业，写入 board_heat）

数据源（findb /api/table，A 股全市场稳定源，替代原 akshare 东财板块接口）：
- 概念：ths_index（type=N 概念指数目录）+ ths_index_daily（指数日线，
  按 ts_code 聚合取最新一根的涨跌幅）。
- 行业：sw_industry（申万行业目录，2021 版一级行业）+ sw_daily
  （申万行业指数日行情，按 ts_code 聚合取最新一根）。

原 akshare 东财概念/行业板块接口已退役：本地常被东财断连/封 IP。

code 口径：findb 板块 ts_code 直接写入（885xxx.TI / 801xxx.SI），
不带 THS: 前缀——后端 /api/boards/heat 按 THS: 前缀判 source=ths，
此处沿用 tushare 风格 ts_code 走默认 eastmoney 分支（与旧东财快照一致）。
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date
from typing import Any

from app.datasource import findb_source
from app.db import get_pool
from app.quality import quality_gate

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


async def _latest_daily_by_code(
    table: str, *, codes: list[str], daily_cols: str
) -> dict[str, dict]:
    """按 ts_code 聚合取指数日线最新一根（单 code 拉取 + 合并，order=desc 取首条）。

    findb 日线表为单 code 接口（sort/order 对全表生效、非按 code 分组），
    逐 code 拉 order=desc limit=1 得到每个指数最新一根。
    单 code 失败只丢该指数，不拖累其余（优雅降级）。
    """
    latest: dict[str, dict] = {}

    async def _one(code: str) -> None:
        rows = await findb_source.fetch_table(
            table, cols=daily_cols, col="ts_code", val=code,
            sort="trade_date", order="desc", limit=1,
        )
        if rows:
            latest[code] = rows[0]

    # 全市场指数目录 ~500 个，分批并发控制请求节奏
    _BATCH = 20
    for i in range(0, len(codes), _BATCH):
        await asyncio.gather(*(_one(c) for c in codes[i : i + _BATCH]))
    return latest


async def _fetch_concept_rows() -> list[tuple]:
    """同花顺概念指数（ths_index type=N + ths_index_daily 最新涨跌幅）。"""
    boards = await findb_source.fetch_table(
        "ths_index", cols="ts_code,name", col="type", val="N", limit=5000
    )
    if not boards:
        logger.warning("findb ths_index 概念目录为空")
        return []

    codes = [str(r["ts_code"]) for r in boards if r.get("ts_code") and r.get("name")]
    latest = await _latest_daily_by_code(
        "ths_index_daily", codes=codes,
        daily_cols="ts_code,pct_change,total_mv,turnover_rate",
    )

    rows = []
    for r in boards:
        code = str(r.get("ts_code") or "")
        name = str(r.get("name") or "").strip()
        if not code or not name:
            continue
        d = latest.get(code, {})
        rows.append((
            "concept",
            name,
            code,
            _f(d.get("pct_change")),
            _i(d.get("total_mv")),
            _f(d.get("turnover_rate")),
            None,  # leader_stock：findb 板块日线无领涨股，置空
            None,  # leader_change：同上
        ))
    logger.info(f"findb concept boards: {len(rows)}")
    return rows


async def _fetch_industry_rows() -> list[tuple]:
    """申万行业（sw_industry 目录 + sw_daily 最新行情）。"""
    boards = await findb_source.fetch_table(
        "sw_industry", cols="ts_code,name", limit=5000
    )
    if not boards:
        logger.warning("findb sw_industry 行业目录为空")
        return []

    codes = [str(r["ts_code"]) for r in boards if r.get("ts_code") and r.get("name")]
    latest = await _latest_daily_by_code(
        "sw_daily", codes=codes,
        daily_cols="ts_code,pct_change,total_mv",
    )

    rows = []
    for r in boards:
        code = str(r.get("ts_code") or "")
        name = str(r.get("name") or "").strip()
        if not code or not name:
            continue
        d = latest.get(code, {})
        rows.append((
            "industry",
            name,
            code,
            _f(d.get("pct_change")),
            _i(d.get("total_mv")),
            None,  # turnover_rate：sw_daily 无换手率，置空
            None,  # leader_stock：findb 行业日线无领涨股，置空
            None,  # leader_change：同上
        ))
    logger.info(f"findb industry boards: {len(rows)}")
    return rows


async def fetch_and_store_boards(board_type: str) -> int:
    """拉一类板块（concept/industry）行情，全量覆盖写入。返回写入条数。"""
    if board_type == "industry":
        rows = await _fetch_industry_rows()
    else:
        rows = await _fetch_concept_rows()

    if not rows:
        logger.warning(f"No boards data for {board_type}")
        return 0

    # 写库前把 tuple 转 dict 过质量闸（键与 board_heat 列名一致；snapshot_date 恒为当天，
    # 与 INSERT 的 DEFAULT CURRENT_DATE 同口径），被拦的行不进 INSERT
    _cols = (
        "board_type", "name", "code", "change_percent", "market_cap",
        "turnover_rate", "leader_stock", "leader_change",
    )
    today = date.today()
    dict_rows = [
        {**dict(zip(_cols, row)), "snapshot_date": today} for row in rows
    ]
    accepted = await quality_gate("board_heat", dict_rows)
    if not accepted:
        logger.warning(f"boards {board_type} 全部被质量闸拦截，保留旧快照")
        return 0
    rows = [tuple(d[c] for c in _cols) for d in accepted]

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


async def run_board_heat_job() -> dict[str, int]:
    """定时任务：拉概念 + 行业板块行情热度"""
    logger.info("=== board heat job start ===")
    counts = {
        "concept": await fetch_and_store_boards("concept"),
        "industry": await fetch_and_store_boards("industry"),
    }
    total = sum(counts.values())
    logger.info(f"=== board heat job done: {total} rows ===")
    return counts
