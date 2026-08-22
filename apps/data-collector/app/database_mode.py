"""数据库 DATA_MODE 身份校验（live/mock 互斥的持久化 marker 机制）。

data-collector 与 data-api 各持一份本模块（同一契约的两个副本）。
collector 作为先启动的写者负责「绑定」数据库身份；data-api 启动时只校验
一致性。metadata 表结构、marker ID、advisory lock ID 两侧必须保持一致，
不得单侧修改。
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any

logger = logging.getLogger(__name__)

METADATA_TABLE = "mock_seed_runs"
MANIFEST_VERSION = 1
DATABASE_MODE_MARKER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
_DATABASE_MODE_LOCK_ID = 8_673_202_608_070_001
_VALID_DATABASE_MODES = {"live", "mock"}

# 业务表清单与 backend 保持一致：用于区分「空库」与「存量库」。
BUSINESS_TABLES = (
    "daily_prices",
    "quote_snapshots",
    "index_prices",
    "movers_cache",
    "news_articles",
    "macro_indicators",
    "income_statements",
    "equity_profiles",
    "fundamental_metrics",
    "board_heat",
    "symbol_board_map",
    "board_sentiment",
    "fund_flow",
    "analyst_consensus",
    "balance_sheets",
    "cash_flow_statements",
    "earnings_calendar",
    "economic_calendar",
    "technical_indicators",
    "announcements",
    "research_reports",
    "market_breadth",
    "macro_asset_prices",
    "yield_curve_rates",
)


def _quote_identifier(value: str) -> str:
    if not re.fullmatch(r"[a-z_][a-z0-9_]*", value):
        raise ValueError(f"非法 SQL 标识符: {value}")
    return f'"{value}"'


async def ensure_metadata_table(conn: Any) -> None:
    """创建专用 metadata 表，不依赖 init.sql 的首次初始化时机。"""
    await conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {METADATA_TABLE} (
            run_id UUID PRIMARY KEY,
            seeded_at TIMESTAMPTZ NOT NULL,
            completed_at TIMESTAMPTZ,
            cleaned_at TIMESTAMPTZ,
            status VARCHAR(30) NOT NULL,
            manifest JSONB NOT NULL,
            error TEXT,
            database_mode VARCHAR(10)
        )
        """
    )
    # 兼容阶段 2 早期已经创建、但还没有数据库身份列的 metadata 表。
    await conn.execute(
        f"ALTER TABLE {METADATA_TABLE} ADD COLUMN IF NOT EXISTS database_mode VARCHAR(10)"
    )
    await conn.execute(
        f"""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_{METADATA_TABLE}_database_mode_singleton
        ON {METADATA_TABLE} ((1))
        WHERE database_mode IS NOT NULL
        """
    )


async def _first_business_table_with_data(conn: Any) -> str | None:
    """返回首个含数据的业务表；未初始化或纯空库返回 None。"""
    existing_rows = await conn.fetch(
        """
        SELECT c.relname
        FROM pg_catalog.pg_class AS c
        JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public'
          AND c.relkind IN ('r', 'p')
          AND c.relname = ANY($1::text[])
        """,
        list(BUSINESS_TABLES),
    )
    existing = {row["relname"] for row in existing_rows}
    for table in BUSINESS_TABLES:
        if table in existing and await conn.fetchval(
            f"SELECT EXISTS (SELECT 1 FROM {_quote_identifier(table)} LIMIT 1)"
        ):
            return table
    return None


async def ensure_database_mode(conn: Any, requested_mode: str) -> str:
    """验证并绑定数据库身份，必须在 scheduler 启动前调用。

    空库可绑定为当前模式；已有业务数据但没有 marker 时只允许迁移为
    live。已绑定数据库与 DATA_MODE 不一致时直接拒绝启动。
    """
    if requested_mode not in _VALID_DATABASE_MODES:
        raise ValueError(f"不支持的数据库模式: {requested_mode!r}")

    await ensure_metadata_table(conn)
    async with conn.transaction():
        # 防止两个进程同时把同一个空库绑定到不同模式。
        await conn.execute("SELECT pg_advisory_xact_lock($1)", _DATABASE_MODE_LOCK_ID)
        marker = await conn.fetchrow(
            f"""
            SELECT run_id, database_mode
            FROM {METADATA_TABLE}
            WHERE database_mode IS NOT NULL
            FOR UPDATE
            """
        )
        if marker is not None:
            database_mode = marker["database_mode"]
            if database_mode not in _VALID_DATABASE_MODES:
                raise RuntimeError(f"数据库 DATA_MODE marker 非法: {database_mode!r}")
            if database_mode != requested_mode:
                raise RuntimeError(
                    "数据库模式不匹配："
                    f"数据库已绑定为 {database_mode!r}，collector 请求 {requested_mode!r}。"
                    "请使用与 DATA_MODE 对应的 PostgreSQL volume。"
                )
            return database_mode

        populated_table = await _first_business_table_with_data(conn)
        if populated_table is not None and requested_mode != "live":
            raise RuntimeError(
                "拒绝把无 marker 的存量数据库绑定为 mock："
                f"业务表 {populated_table!r} 已有数据。"
                "存量数据库只能先以 DATA_MODE=live 启动完成身份迁移。"
            )

        manifest = json.dumps(
            {
                "version": MANIFEST_VERSION,
                "database_mode": requested_mode,
                "migration": "existing-live" if populated_table else "empty-database",
            },
            ensure_ascii=False,
        )
        await conn.execute(
            f"""
            INSERT INTO {METADATA_TABLE} (
                run_id, seeded_at, completed_at, status, manifest, database_mode
            )
            VALUES ($1, NOW(), NOW(), 'database-mode', $2::jsonb, $3)
            """,
            DATABASE_MODE_MARKER_ID,
            manifest,
            requested_mode,
        )
        logger.info("数据库身份已绑定为 %s", requested_mode)
        return requested_mode
