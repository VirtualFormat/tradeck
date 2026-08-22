"""mock 数据运行清单、审计与保守清理工具。

用法：

    python -m app.mock_data audit
    python -m app.mock_data clean          # 默认仅演练
    python -m app.mock_data clean --apply  # 事务化执行
    python -m app.mock_data legacy-audit --date 2026-08-07
    python -m app.mock_data legacy-clean --date 2026-08-07 [--apply]

清理原则：只处理有完整 seed manifest 或强 mock 标记的记录。历史库中
无标记的行一律报告为“不可安全识别”，日期、价格、固定标的等弱特征
不会参与判断。
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import random
import re
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Iterable, Mapping, Sequence

from app.db import close_pool, get_pool

logger = logging.getLogger(__name__)

METADATA_TABLE = "mock_seed_runs"
MANIFEST_VERSION = 1
DATABASE_MODE_MARKER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
_DATABASE_MODE_LOCK_ID = 8_673_202_608_070_001
_VALID_DATABASE_MODES = {"live", "mock"}
LEGACY_RECIPE_VERSION = "seed-v1-2026-08-07"
LEGACY_RECIPE_DATE = date(2026, 8, 7)
LEGACY_RECIPE_ROW_COUNT = 32_003
LEGACY_RECIPE_SHA256 = "589d9f6cb2b437cda7339b6db435821ae8ffffaa522269829ffaef7b63a56f57"
_CLEAN_BATCH_SIZE = 500
_COLUMN_TYPE_CACHE: dict[tuple[str, tuple[str, ...]], dict[str, str]] = {}

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

# seed 写入使用的业务唯一键。manifest 还会同时保存数据库物理主键。
LOGICAL_KEYS: dict[str, tuple[str, ...]] = {
    "quote_snapshots": ("symbol",),
    "daily_prices": ("symbol", "date"),
    "index_prices": ("symbol", "date"),
    "movers_cache": ("type", "market", "rank", "symbol", "snapshot_date"),
    "news_articles": ("url",),
    "macro_indicators": ("name", "date"),
    "equity_profiles": ("symbol",),
    "fundamental_metrics": ("symbol",),
    "income_statements": ("symbol", "fiscal_year"),
    "board_heat": ("board_type", "name", "snapshot_date"),
    "analyst_consensus": ("symbol", "snapshot_date"),
    "balance_sheets": ("symbol", "period", "fiscal_date"),
    "cash_flow_statements": ("symbol", "period", "fiscal_date"),
    "earnings_calendar": ("symbol", "report_date"),
    "economic_calendar": ("event_date", "event_name", "country"),
    "announcements": ("symbol", "title", "publish_date"),
    "research_reports": ("symbol", "title", "publish_date"),
    "market_breadth": ("date", "market"),
    "macro_asset_prices": ("symbol", "date"),
    "yield_curve_rates": ("date",),
}

PRIMARY_KEYS: dict[str, tuple[str, ...]] = {
    "quote_snapshots": ("symbol",),
    "daily_prices": ("id",),
    "index_prices": ("id",),
    "movers_cache": ("id",),
    "news_articles": ("id",),
    "macro_indicators": ("id",),
    "equity_profiles": ("symbol",),
    "fundamental_metrics": ("symbol",),
    "income_statements": ("id",),
    "board_heat": ("id",),
    "analyst_consensus": ("symbol", "snapshot_date"),
    "balance_sheets": ("symbol", "period", "fiscal_date"),
    "cash_flow_statements": ("symbol", "period", "fiscal_date"),
    "earnings_calendar": ("symbol", "report_date"),
    "economic_calendar": ("event_date", "event_name", "country"),
    "announcements": ("symbol", "title", "publish_date"),
    "research_reports": ("symbol", "title", "publish_date"),
    "market_breadth": ("date", "market"),
    "macro_asset_prices": ("symbol", "date"),
    "yield_curve_rates": ("date",),
}

STRONG_EVIDENCE_SQL: dict[str, str] = {
    "news_articles": "url LIKE 'https://mock.tradeck.dev/%' OR summary LIKE '%dev 种子脚本生成%'",
    "equity_profiles": "description LIKE '%dev 种子脚本生成%'",
    "announcements": "url LIKE 'https://mock.tradeck.dev/%'",
    "research_reports": "url LIKE 'https://mock.tradeck.dev/%'",
    "market_breadth": "source = 'mock'",
}

_INSERT_RE = re.compile(
    r"INSERT\s+INTO\s+([a-z_][a-z0-9_]*)\s*\((.*?)\)\s*VALUES",
    re.IGNORECASE | re.DOTALL,
)

@dataclass(frozen=True)
class SeedRun:
    run_id: uuid.UUID
    seeded_at: datetime


@dataclass(frozen=True)
class ExpectedRow:
    table: str
    values: dict[str, Any]


@dataclass(frozen=True)
class LegacyCandidate:
    table: str
    logical_key: dict[str, Any]
    primary_key: dict[str, Any]
    fingerprint: dict[str, Any]


@dataclass(frozen=True)
class LegacySelection:
    candidates: tuple[LegacyCandidate, ...]
    replayed_tables: tuple[str, ...]
    replayed_counts: dict[str, int]


@dataclass(frozen=True)
class Candidate:
    table: str
    primary_key: dict[str, Any]
    fingerprint: dict[str, Any]
    evidence: str
    restore_row: dict[str, Any] | None = None
    manifest_run_ids: tuple[uuid.UUID, ...] = ()


@dataclass(frozen=True)
class ManifestSelection:
    run_ids: tuple[uuid.UUID, ...] = ()
    total_chains: int = 0
    skipped_chains: int = 0


def _quote_identifier(value: str) -> str:
    if not re.fullmatch(r"[a-z_][a-z0-9_]*", value):
        raise ValueError(f"非法 SQL 标识符: {value}")
    return f'"{value}"'


def _encode_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, Decimal):
        return {"$decimal": str(value)}
    if isinstance(value, datetime):
        return {"$datetime": value.isoformat()}
    if isinstance(value, date):
        return {"$date": value.isoformat()}
    if isinstance(value, float):
        return {"$float": repr(value)}
    raise TypeError(f"manifest 不支持的值类型: {type(value)!r}")


def _decode_value(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    if "$decimal" in value:
        return Decimal(value["$decimal"])
    if "$datetime" in value:
        return datetime.fromisoformat(value["$datetime"])
    if "$date" in value:
        return date.fromisoformat(value["$date"])
    if "$float" in value:
        return float(value["$float"])
    raise ValueError(f"未知 manifest 值: {value!r}")


def _encode_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {key: _encode_value(value) for key, value in row.items()}


def _decode_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {key: _decode_value(value) for key, value in row.items()}


def _stable_key(values: Mapping[str, Any], columns: Sequence[str]) -> str:
    encoded = [_encode_value(values[column]) for column in columns]
    return json.dumps(encoded, ensure_ascii=False, sort_keys=True)


def _parse_insert(sql: str, args: Iterable[Sequence[Any]]) -> tuple[str, list[ExpectedRow]]:
    match = _INSERT_RE.search(sql)
    if not match:
        raise ValueError("seed recorder 只能记录带显式列清单的 INSERT")
    table = match.group(1).lower()
    if table not in LOGICAL_KEYS:
        raise ValueError(f"seed 写入了未登记的表: {table}")
    columns = [part.strip().strip('"').lower() for part in match.group(2).split(",")]
    values_match = re.search(
        r"\bVALUES\s*\((.*?)\)", sql[match.end() - len("VALUES") :], re.IGNORECASE | re.DOTALL
    )
    if not values_match:
        raise ValueError(f"{table} INSERT 缺少 VALUES 参数清单")
    value_tokens = [part.strip() for part in values_match.group(1).split(",")]
    if len(columns) != len(value_tokens):
        raise ValueError(f"{table} INSERT 列清单与 VALUES 清单长度不一致")
    parameter_columns: list[tuple[int, str]] = []
    for column, token in zip(columns, value_tokens):
        parameter_match = re.fullmatch(r"\$(\d+)(?:::[a-z0-9_]+)?", token, re.IGNORECASE)
        if parameter_match:
            parameter_columns.append((int(parameter_match.group(1)) - 1, column))
    rows = []
    for values in args:
        if not parameter_columns or max(index for index, _ in parameter_columns) >= len(values):
            raise ValueError(f"{table} INSERT 参数清单无法解析")
        rows.append(
            ExpectedRow(
                table=table,
                values={column: values[index] for index, column in parameter_columns},
            )
        )
    return table, rows


def _expected_identity(expected: ExpectedRow, current_date: date) -> dict[str, Any]:
    identity: dict[str, Any] = {}
    for column in LOGICAL_KEYS[expected.table]:
        if column in expected.values:
            identity[column] = expected.values[column]
        elif column == "snapshot_date":
            identity[column] = current_date
        else:
            raise ValueError(f"{expected.table} 缺少业务键字段 {column}")
    return identity


class SeedCaptureConnection:
    """只捕获 legacy seed 的显式 INSERT 参数，不连接或写入数据库。"""

    def __init__(self, current_date: date) -> None:
        self.current_date = current_date
        self.rows: list[ExpectedRow] = []
        self.tables: list[str] = []

    async def executemany(self, sql: str, args: Iterable[Sequence[Any]]) -> None:
        table, expected = _parse_insert(sql, list(args))
        for row in expected:
            _expected_identity(row, self.current_date)
        if table not in self.tables:
            self.tables.append(table)
        self.rows.extend(expected)


async def _replay_legacy_seed(target_date: date) -> SeedCaptureConnection:
    """重放冻结的 2026-08-07 seed-v1 配方；全程只使用内存。"""
    if target_date != LEGACY_RECIPE_DATE:
        raise ValueError(
            f"legacy 配方 {LEGACY_RECIPE_VERSION} 仅适用于 "
            f"{LEGACY_RECIPE_DATE.isoformat()}"
        )
    from app import seed_mock

    original_rng = seed_mock.rng
    original_date = seed_mock.date

    class CapturedDate(original_date):
        @classmethod
        def today(cls) -> date:
            return target_date

    capture = SeedCaptureConnection(target_date)
    seed_mock.rng = random.Random(42)
    seed_mock.date = CapturedDate
    try:
        quotes = await seed_mock.seed_quotes(capture)
        await seed_mock.seed_daily_prices(capture, quotes)
        await seed_mock.seed_index_prices(capture)
        await seed_mock.seed_movers(capture, quotes)
        # seed_news 本身不重放，但需消耗相同随机数，保持后续 seed 指纹不偏移。
        news_publishers = ("华尔街见闻", "财联社", "彭博社", "路透中文网", "证券时报")
        for _ in seed_mock.NEWS_TITLES:
            seed_mock.rng.choice(news_publishers)
            seed_mock.rng.randint(0, 2)
        await seed_mock.seed_macro(capture)
        await seed_mock.seed_fundamentals(capture, quotes)
        await seed_mock.seed_analyst_consensus(capture, quotes)
        await seed_mock.seed_balance_cash(capture, quotes)
        await seed_mock.seed_boards(capture)
        await seed_mock.seed_earnings_calendar(capture)
        await seed_mock.seed_economic_calendar(capture)
        await seed_mock.seed_announcements(capture)
        await seed_mock.seed_research_reports(capture)
        await seed_mock.seed_market_breadth(capture)
        await seed_mock.seed_macro_asset_prices(capture)
        await seed_mock.seed_yield_curve_rates(capture)
    finally:
        seed_mock.rng = original_rng
        seed_mock.date = original_date
    payload = [
        [
            row.table,
            [[key, _encode_value(value)] for key, value in sorted(row.values.items())],
        ]
        for row in capture.rows
    ]
    digest = hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    if len(capture.rows) != LEGACY_RECIPE_ROW_COUNT or digest != LEGACY_RECIPE_SHA256:
        raise RuntimeError(
            "legacy seed 配方已漂移，拒绝审计或清理："
            f"rows={len(capture.rows)}, sha256={digest}"
        )
    return capture


def _legacy_value_matches(expected: Any, actual: Any) -> bool:
    if expected is None:
        return actual is None
    if isinstance(expected, bool):
        return isinstance(actual, bool) and expected == actual
    numeric_types = (Decimal, int, float)
    if isinstance(expected, numeric_types):
        if isinstance(actual, bool) or not isinstance(actual, numeric_types):
            return False
        try:
            return Decimal(str(expected)).normalize() == Decimal(str(actual)).normalize()
        except ArithmeticError:
            return False
    if isinstance(expected, str):
        return isinstance(actual, str) and expected == actual
    if isinstance(expected, datetime):
        return isinstance(actual, datetime) and expected == actual
    if isinstance(expected, date):
        return isinstance(actual, date) and not isinstance(actual, datetime) and expected == actual
    return type(expected) is type(actual) and expected == actual


def _legacy_row_matches(fingerprint: Mapping[str, Any], actual: Mapping[str, Any]) -> bool:
    return all(
        column in actual and _legacy_value_matches(expected, actual[column])
        for column, expected in fingerprint.items()
    )


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
    """验证并绑定数据库身份，必须在 seed 或 scheduler 启动前调用。

    空库可绑定为当前模式；已有业务数据但没有 marker 时只允许迁移为
    live。已绑定数据库与 DATA_MODE 不一致时直接拒绝启动。
    """
    if requested_mode not in _VALID_DATABASE_MODES:
        raise ValueError(f"不支持的数据库模式: {requested_mode!r}")

    await ensure_metadata_table(conn)
    async with conn.transaction():
        # 防止两个 backend 同时把同一个空库绑定到不同模式。
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
                raise RuntimeError(
                    f"数据库 DATA_MODE marker 非法: {database_mode!r}"
                )
            if database_mode != requested_mode:
                raise RuntimeError(
                    "数据库模式不匹配："
                    f"数据库已绑定为 {database_mode!r}，backend 请求 {requested_mode!r}。"
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
        return requested_mode


async def begin_seed_run(conn: Any) -> SeedRun:
    """seed 开始前先提交一条 running 记录，失败也可追溯。"""
    await ensure_metadata_table(conn)
    run = SeedRun(run_id=uuid.uuid4(), seeded_at=datetime.now(timezone.utc))
    before_manifest = {
        "version": MANIFEST_VERSION,
        "phase": "before",
        "tables": {},
    }
    await conn.execute(
        f"""
        INSERT INTO {METADATA_TABLE} (run_id, seeded_at, status, manifest)
        VALUES ($1, $2, 'running', $3::jsonb)
        """,
        run.run_id,
        run.seeded_at,
        json.dumps(before_manifest, ensure_ascii=False),
    )
    return run


async def fail_seed_run(conn: Any, run: SeedRun, error: BaseException) -> None:
    await conn.execute(
        f"""
        UPDATE {METADATA_TABLE}
        SET status = 'failed', completed_at = NOW(), error = $2
        WHERE run_id = $1
        """,
        run.run_id,
        str(error)[:4000],
    )


class SeedRecordingConnection:
    """在不改各 seed 函数签名的前提下记录每次 INSERT 的 before/after。"""

    def __init__(self, conn: Any, current_date: date) -> None:
        self._conn = conn
        self.current_date = current_date
        self.mutations: list[dict[str, Any]] = []

    def transaction(self, *args: Any, **kwargs: Any) -> Any:
        return self._conn.transaction(*args, **kwargs)

    async def execute(self, sql: str, *args: Any) -> Any:
        return await self._conn.execute(sql, *args)

    async def executemany(self, sql: str, args: Iterable[Sequence[Any]]) -> Any:
        materialized = list(args)
        table, expected = _parse_insert(sql, materialized)
        identities = [self._identity(item) for item in expected]
        before = await _fetch_rows(self._conn, table, LOGICAL_KEYS[table], identities)
        result = await self._conn.executemany(sql, materialized)
        after = await _fetch_rows(self._conn, table, LOGICAL_KEYS[table], identities)

        for identity in identities:
            key = _stable_key(identity, LOGICAL_KEYS[table])
            actual = after.get(key)
            if actual is None:
                raise RuntimeError(f"{table} seed 后无法按业务键回读记录: {identity}")
            primary_key = {
                column: actual[column]
                for column in PRIMARY_KEYS[table]
            }
            self.mutations.append(
                {
                    "table": table,
                    "logical_key": _encode_row(identity),
                    "primary_key": _encode_row(primary_key),
                    "before": _encode_row(before[key]) if key in before else None,
                    "after": _encode_row(actual),
                }
            )
        return result

    def _identity(self, expected: ExpectedRow) -> dict[str, Any]:
        return _expected_identity(expected, self.current_date)


async def complete_seed_run(
    conn: Any,
    run: SeedRun,
    recorder: SeedRecordingConnection,
    counts: Mapping[str, int],
) -> None:
    tables: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for mutation in recorder.mutations:
        tables[mutation["table"]].append(
            {key: value for key, value in mutation.items() if key != "table"}
        )
    manifest = {
        "version": MANIFEST_VERSION,
        "phase": "after",
        "counts": dict(counts),
        "tables": dict(tables),
    }
    await conn.execute(
        f"""
        UPDATE {METADATA_TABLE}
        SET status = 'complete', completed_at = NOW(), manifest = $2::jsonb, error = NULL
        WHERE run_id = $1
        """,
        run.run_id,
        json.dumps(manifest, ensure_ascii=False),
    )


async def _fetch_rows(
    conn: Any,
    table: str,
    columns: Sequence[str],
    identities: Sequence[Mapping[str, Any]],
    *,
    for_update: bool = False,
) -> dict[str, dict[str, Any]]:
    """按复合键分批做唯一索引点查，避免巨型 OR 退化为全表扫描。"""
    if not identities:
        return {}
    result: dict[str, dict[str, Any]] = {}
    quoted_table = _quote_identifier(table)
    quoted_columns = [_quote_identifier(column) for column in columns]
    cache_key = (table, tuple(columns))
    column_types = _COLUMN_TYPE_CACHE.get(cache_key)
    if column_types is None:
        type_rows = await conn.fetch(
            """
            SELECT attribute.attname,
                   pg_catalog.format_type(attribute.atttypid, attribute.atttypmod) AS data_type
            FROM pg_catalog.pg_attribute AS attribute
            WHERE attribute.attrelid = $1::regclass
              AND attribute.attname = ANY($2::text[])
              AND attribute.attnum > 0
              AND NOT attribute.attisdropped
            """,
            table,
            list(columns),
        )
        column_types = {row["attname"]: row["data_type"] for row in type_rows}
        _COLUMN_TYPE_CACHE[cache_key] = column_types
    if set(column_types) != set(columns):
        missing = sorted(set(columns) - set(column_types))
        raise ValueError(f"{table} 缺少业务键列: {missing}")
    for offset in range(0, len(identities), _CLEAN_BATCH_SIZE):
        chunk = identities[offset : offset + _CLEAN_BATCH_SIZE]
        params: list[Any] = []
        value_rows = []
        for identity in chunk:
            placeholders = []
            for column in columns:
                params.append(identity[column])
                placeholders.append(f"${len(params)}::{column_types[column]}")
            value_rows.append("(" + ", ".join(placeholders) + ")")
        comparisons = " AND ".join(
            f'target.{column} = lookup.{column}' for column in quoted_columns
        )
        lock = " FOR UPDATE OF target" if for_update else ""
        rows = await conn.fetch(
            f"""
            SELECT matched.*
            FROM (VALUES {', '.join(value_rows)})
                AS lookup ({', '.join(quoted_columns)})
            CROSS JOIN LATERAL (
                SELECT target.*
                FROM {quoted_table} AS target
                WHERE {comparisons}
                LIMIT 1{lock}
            ) AS matched
            """,
            *params,
        )
        for record in rows:
            row = dict(record)
            result[_stable_key(row, columns)] = row
    return result


async def _legacy_candidates(
    conn: Any,
    target_date: date,
    recipe: str = LEGACY_RECIPE_VERSION,
) -> LegacySelection:
    if recipe != LEGACY_RECIPE_VERSION:
        raise ValueError(f"不支持的 legacy 配方: {recipe}")
    capture = await _replay_legacy_seed(target_date)
    expected_by_table: dict[str, dict[str, tuple[dict[str, Any], dict[str, Any]]]] = {
        table: {} for table in capture.tables
    }
    for expected in capture.rows:
        logical_key = _expected_identity(expected, target_date)
        stable_key = _stable_key(logical_key, LOGICAL_KEYS[expected.table])
        fingerprint = dict(expected.values)
        previous = expected_by_table[expected.table].get(stable_key)
        if previous is not None and previous[1] != fingerprint:
            raise ValueError(
                f"{expected.table} legacy seed 对同一业务键生成了不同显式参数指纹"
            )
        expected_by_table[expected.table][stable_key] = (logical_key, fingerprint)

    candidates: list[LegacyCandidate] = []
    replayed_counts: dict[str, int] = {}
    for table in capture.tables:
        expected_rows = expected_by_table[table]
        replayed_counts[table] = len(expected_rows)
        actual_rows = await _fetch_rows(
            conn,
            table,
            LOGICAL_KEYS[table],
            [logical_key for logical_key, _ in expected_rows.values()],
        )
        for stable_key, (logical_key, fingerprint) in expected_rows.items():
            actual = actual_rows.get(stable_key)
            if actual is None or not _legacy_row_matches(fingerprint, actual):
                continue
            candidates.append(
                LegacyCandidate(
                    table=table,
                    logical_key=logical_key,
                    primary_key={
                        column: actual[column] for column in PRIMARY_KEYS[table]
                    },
                    fingerprint=fingerprint,
                )
            )
    return LegacySelection(
        candidates=tuple(candidates),
        replayed_tables=tuple(capture.tables),
        replayed_counts=replayed_counts,
    )


def _print_legacy_selection(
    selection: LegacySelection,
    target_date: date,
    *,
    heading: str,
) -> None:
    counts = _counts_by_table(selection.candidates)
    print(f"{heading}（seed 日期 {target_date.isoformat()}）：")
    for table in selection.replayed_tables:
        print(
            f"  {table}: 候选 {counts.get(table, 0)} / "
            f"重放 {selection.replayed_counts[table]}"
        )
    print("  news_articles: 跳过（seed_news 依赖精确时间；已有强 mock 证据清理）")
    print(f"合计 legacy seed 候选: {len(selection.candidates)}")


async def legacy_audit(
    conn: Any,
    target_date: date,
    recipe: str = LEGACY_RECIPE_VERSION,
) -> dict[str, int]:
    async with conn.transaction():
        selection = await _legacy_candidates(conn, target_date, recipe)
    _print_legacy_selection(selection, target_date, heading="legacy seed 精确审计")
    return _counts_by_table(selection.candidates)


async def _delete_primary_keys(
    conn: Any,
    table: str,
    primary_keys: Sequence[Mapping[str, Any]],
) -> int:
    """用单条 VALUES JOIN 批量删除已复核的主键。"""
    if not primary_keys:
        return 0
    columns = PRIMARY_KEYS[table]
    cache_key = (table, tuple(columns))
    column_types = _COLUMN_TYPE_CACHE.get(cache_key)
    if column_types is None:
        # 复用点查以填充列类型缓存；结果不参与删除判断。
        await _fetch_rows(conn, table, columns, primary_keys[:1])
        column_types = _COLUMN_TYPE_CACHE[cache_key]
    params: list[Any] = []
    value_rows: list[str] = []
    for primary_key in primary_keys:
        placeholders = []
        for column in columns:
            params.append(primary_key[column])
            placeholders.append(f"${len(params)}::{column_types[column]}")
        value_rows.append("(" + ", ".join(placeholders) + ")")
    quoted_columns = [_quote_identifier(column) for column in columns]
    comparisons = " AND ".join(
        f"target.{column} = doomed.{column}" for column in quoted_columns
    )
    result = await conn.execute(
        f"""
        DELETE FROM {_quote_identifier(table)} AS target
        USING (VALUES {', '.join(value_rows)})
            AS doomed ({', '.join(quoted_columns)})
        WHERE {comparisons}
        """,
        *params,
    )
    return int(result.rsplit(" ", 1)[-1])


async def _clean_legacy_table(
    conn: Any,
    table: str,
    candidates: Sequence[LegacyCandidate],
) -> tuple[int, int]:
    """按 500 条一批锁定、完整复核并批量删除；单表一个事务。"""
    deleted = 0
    skipped = 0
    logical_columns = LOGICAL_KEYS[table]
    async with conn.transaction():
        for offset in range(0, len(candidates), _CLEAN_BATCH_SIZE):
            chunk = candidates[offset : offset + _CLEAN_BATCH_SIZE]
            locked = await _fetch_rows(
                conn,
                table,
                logical_columns,
                [candidate.logical_key for candidate in chunk],
                for_update=True,
            )
            safe_primary_keys: list[dict[str, Any]] = []
            for candidate in chunk:
                actual = locked.get(
                    _stable_key(candidate.logical_key, logical_columns)
                )
                if (
                    actual is None
                    or not _legacy_row_matches(candidate.fingerprint, actual)
                    or any(
                        not _legacy_value_matches(value, actual.get(column))
                        for column, value in candidate.primary_key.items()
                    )
                ):
                    skipped += 1
                    continue
                safe_primary_keys.append(candidate.primary_key)
            deleted += await _delete_primary_keys(conn, table, safe_primary_keys)
    return deleted, skipped


async def legacy_clean(
    conn: Any,
    target_date: date,
    *,
    apply: bool,
    recipe: str = LEGACY_RECIPE_VERSION,
) -> None:
    deleted: dict[str, int] = defaultdict(int)
    skipped = 0
    selection = await _legacy_candidates(conn, target_date, recipe)
    if apply:
        await ensure_metadata_table(conn)
        database_mode = await conn.fetchval(
            f"SELECT database_mode FROM {METADATA_TABLE} "
            "WHERE database_mode IS NOT NULL"
        )
        if database_mode != "live":
            raise RuntimeError(
                "legacy clean --apply 仅允许在带 live marker 的数据库执行；"
                f"当前 marker={database_mode!r}"
            )
        print(f"数据库身份: {database_mode}")
        grouped: dict[str, list[LegacyCandidate]] = defaultdict(list)
        for candidate in selection.candidates:
            grouped[candidate.table].append(candidate)
        for table in selection.replayed_tables:
            table_candidates = grouped.get(table, [])
            if not table_candidates:
                continue
            table_deleted, table_skipped = await _clean_legacy_table(
                conn,
                table,
                table_candidates,
            )
            deleted[table] = table_deleted
            skipped += table_skipped
            print(
                f"  {table}: 已删除 {table_deleted}，复核跳过 {table_skipped}",
                flush=True,
            )

    heading = "legacy seed 执行清理" if apply else "legacy seed DRY-RUN（未删除）"
    _print_legacy_selection(selection, target_date, heading=heading)
    if apply:
        print(f"实际删除: {sum(deleted.values())}；复核后跳过: {skipped}")


async def _manifest_candidates(
    conn: Any,
) -> tuple[dict[tuple[str, str], Candidate], ManifestSelection]:
    rows = await conn.fetch(
        f"""
        SELECT run_id, manifest
        FROM {METADATA_TABLE}
        WHERE status = 'complete'
        ORDER BY seeded_at DESC
        """
    )
    entries: dict[str, dict[str, list[tuple[uuid.UUID, dict[str, Any]]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    run_ids: list[uuid.UUID] = []
    skipped_chains = 0
    for row in rows:
        run_ids.append(row["run_id"])
        manifest = row["manifest"]
        if isinstance(manifest, str):
            manifest = json.loads(manifest)
        if manifest.get("version") != MANIFEST_VERSION:
            logger.warning("跳过未知版本 manifest: %s", manifest.get("version"))
            skipped_chains += 1
            continue
        for table, mutations in manifest.get("tables", {}).items():
            pk_columns = PRIMARY_KEYS.get(table)
            if not pk_columns:
                skipped_chains += 1
                continue
            for mutation in mutations:
                identity = _decode_row(mutation["primary_key"])
                key = _stable_key(identity, pk_columns)
                entries[table][key].append((row["run_id"], mutation))

    candidates: dict[tuple[str, str], Candidate] = {}
    total_chains = sum(len(chains) for chains in entries.values())
    for table, mutation_chains in entries.items():
        pk_columns = PRIMARY_KEYS.get(table)
        if not pk_columns:
            continue
        # 查询按 seeded_at DESC，每条链第一项是当前应匹配的最新指纹。
        mutations = [chain[0][1] for chain in mutation_chains.values()]
        identities = [_decode_row(item["primary_key"]) for item in mutations]
        current = await _fetch_rows(conn, table, pk_columns, identities)
        for item, identity in zip(mutations, identities):
            key = _stable_key(identity, pk_columns)
            actual = current.get(key)
            if actual is None or _encode_row(actual) != item["after"]:
                skipped_chains += 1
                continue
            # 连续多次 seed 时沿 before/after 链回溯到最初状态。
            restore_row = item["before"]
            chain_run_ids = [mutation_chains[key][0][0]]
            for older_run_id, older in mutation_chains[key][1:]:
                if restore_row is None or older["after"] != restore_row:
                    skipped_chains += 1
                    break
                restore_row = older["before"]
                chain_run_ids.append(older_run_id)
            candidates[(table, key)] = Candidate(
                table=table,
                primary_key=identity,
                fingerprint=item["after"],
                evidence="manifest 精确指纹",
                restore_row=restore_row,
                manifest_run_ids=tuple(chain_run_ids),
            )
    return candidates, ManifestSelection(
        run_ids=tuple(run_ids),
        total_chains=total_chains,
        skipped_chains=skipped_chains,
    )


async def _strong_candidates(conn: Any) -> dict[tuple[str, str], Candidate]:
    candidates: dict[tuple[str, str], Candidate] = {}
    for table, predicate in STRONG_EVIDENCE_SQL.items():
        rows = await conn.fetch(
            f"SELECT * FROM {_quote_identifier(table)} WHERE {predicate}"
        )
        pk_columns = PRIMARY_KEYS[table]
        for record in rows:
            row = dict(record)
            primary_key = {column: row[column] for column in pk_columns}
            key = _stable_key(primary_key, pk_columns)
            candidates[(table, key)] = Candidate(
                table=table,
                primary_key=primary_key,
                fingerprint=_encode_row(row),
                evidence="URL/description/source 强 mock 证据",
            )
    return candidates


async def collect_candidates(
    conn: Any,
) -> tuple[dict[tuple[str, str], Candidate], ManifestSelection]:
    """合并强证据和 manifest；同一行优先保留可逆的 manifest。"""
    candidates = await _strong_candidates(conn)
    manifest_candidates, selection = await _manifest_candidates(conn)
    candidates.update(manifest_candidates)
    return candidates, selection


async def _has_complete_manifests(conn: Any) -> bool:
    return bool(
        await conn.fetchval(
            f"SELECT EXISTS (SELECT 1 FROM {METADATA_TABLE} WHERE status = 'complete')"
        )
    )


def _counts_by_table(candidates: Iterable[Candidate]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for candidate in candidates:
        counts[candidate.table] += 1
    return dict(sorted(counts.items()))


async def audit(conn: Any) -> dict[str, int]:
    await ensure_metadata_table(conn)
    async with conn.transaction():
        candidates, selection = await collect_candidates(conn)
        has_manifests = bool(selection.run_ids)
    counts = _counts_by_table(candidates.values())
    print("24 张业务表 mock 审计：")
    for table in BUSINESS_TABLES:
        count = counts.get(table, 0)
        if count:
            print(f"  {table}: 可识别 {count} 条")
        elif table not in LOGICAL_KEYS:
            print(f"  {table}: 0 条（seed 不写入此表）")
        elif table in STRONG_EVIDENCE_SQL:
            print(f"  {table}: 0 条（当前无强标记或匹配 manifest）")
        elif has_manifests:
            print(f"  {table}: 0 条（未匹配 manifest；已被改写或本次未 seed）")
        else:
            print(f"  {table}: 0 条（历史无标记，不可安全识别；仅未来 manifest 可逆）")
    print(f"合计可明确识别: {sum(counts.values())}")
    return counts


async def _table_totals(conn: Any, tables: Iterable[str]) -> dict[str, int]:
    totals = {}
    for table in sorted(set(tables)):
        totals[table] = await conn.fetchval(
            f"SELECT COUNT(*) FROM {_quote_identifier(table)}"
        )
    return totals


def _has_strong_evidence(table: str, row: Mapping[str, Any]) -> bool:
    if table == "news_articles":
        return str(row.get("url") or "").startswith("https://mock.tradeck.dev/") or (
            "dev 种子脚本生成" in str(row.get("summary") or "")
        )
    if table == "equity_profiles":
        return "dev 种子脚本生成" in str(row.get("description") or "")
    if table in {"announcements", "research_reports"}:
        return str(row.get("url") or "").startswith("https://mock.tradeck.dev/")
    if table == "market_breadth":
        return row.get("source") == "mock"
    return False


def _candidate_matches(candidate: Candidate, actual: Mapping[str, Any] | None) -> bool:
    if actual is None:
        return False
    if candidate.evidence == "manifest 精确指纹":
        return _encode_row(actual) == candidate.fingerprint
    return _has_strong_evidence(candidate.table, actual)


async def _restore_candidate(conn: Any, candidate: Candidate) -> None:
    """恢复一条已在当前批事务中锁定并复核的 seed 前记录。"""
    if candidate.restore_row is None:
        raise ValueError("缺少 manifest seed 前记录，不能执行恢复")
    table = candidate.table
    pk_columns = PRIMARY_KEYS[table]
    params = [candidate.primary_key[column] for column in pk_columns]
    where = " AND ".join(
        f"{_quote_identifier(column)} = ${index}"
        for index, column in enumerate(pk_columns, 1)
    )
    restore = _decode_row(candidate.restore_row)
    columns = list(restore)
    assignments = ", ".join(
        f"{_quote_identifier(column)} = ${len(params) + index}"
        for index, column in enumerate(columns, 1)
    )
    result = await conn.execute(
        f"UPDATE {_quote_identifier(table)} SET {assignments} WHERE {where}",
        *params,
        *(restore[column] for column in columns),
    )
    if result != "UPDATE 1":
        raise RuntimeError(
            f"{table} manifest 恢复影响行数异常: {result}; "
            f"primary_key={candidate.primary_key}"
        )


async def _clean_candidate_batch(
    conn: Any,
    table: str,
    candidates: Sequence[Candidate],
) -> tuple[int, int, int, int]:
    """短事务内批量锁定复核，批量删除并逐条恢复。"""
    if not candidates:
        return 0, 0, 0, 0
    if len(candidates) > _CLEAN_BATCH_SIZE:
        raise ValueError(f"单批清理不能超过 {_CLEAN_BATCH_SIZE} 条")
    if any(candidate.table != table for candidate in candidates):
        raise ValueError("同一清理批次只能包含一张表")

    deleted = 0
    restored = 0
    manifest_skips = 0
    verification_skips = 0
    pk_columns = PRIMARY_KEYS[table]
    async with conn.transaction():
        locked = await _fetch_rows(
            conn,
            table,
            pk_columns,
            [candidate.primary_key for candidate in candidates],
            for_update=True,
        )
        delete_keys: list[dict[str, Any]] = []
        restore_candidates: list[Candidate] = []
        for candidate in candidates:
            actual = locked.get(_stable_key(candidate.primary_key, pk_columns))
            if not _candidate_matches(candidate, actual):
                verification_skips += 1
                if candidate.manifest_run_ids:
                    manifest_skips += 1
                continue
            if candidate.restore_row is None:
                delete_keys.append(candidate.primary_key)
            else:
                restore_candidates.append(candidate)

        deleted = await _delete_primary_keys(conn, table, delete_keys)
        if deleted != len(delete_keys):
            raise RuntimeError(
                f"{table} manifest 批量删除影响行数异常: "
                f"预期 {len(delete_keys)}，实际 {deleted}"
            )
        for candidate in restore_candidates:
            await _restore_candidate(conn, candidate)
            restored += 1
    return deleted, restored, manifest_skips, verification_skips


async def _clean_candidate_table(
    conn: Any,
    table: str,
    candidates: Sequence[Candidate],
) -> tuple[int, int, int, int]:
    """按 500 条短事务处理一张表，避免跨表或全量长事务。"""
    deleted = 0
    restored = 0
    manifest_skips = 0
    verification_skips = 0
    for offset in range(0, len(candidates), _CLEAN_BATCH_SIZE):
        chunk = candidates[offset : offset + _CLEAN_BATCH_SIZE]
        batch_deleted, batch_restored, batch_manifest_skips, batch_skips = (
            await _clean_candidate_batch(conn, table, chunk)
        )
        deleted += batch_deleted
        restored += batch_restored
        manifest_skips += batch_manifest_skips
        verification_skips += batch_skips
    return deleted, restored, manifest_skips, verification_skips


async def clean(conn: Any, *, apply: bool) -> None:
    await ensure_metadata_table(conn)
    candidates, selection = await collect_candidates(conn)
    has_manifests = bool(selection.run_ids)
    before = await _table_totals(conn, BUSINESS_TABLES)
    deleted: dict[str, int] = defaultdict(int)
    restored: dict[str, int] = defaultdict(int)
    manifest_skips = selection.skipped_chains
    verification_skips = 0

    grouped: dict[str, list[Candidate]] = defaultdict(list)
    for candidate in candidates.values():
        grouped[candidate.table].append(candidate)

    if apply:
        # 每表按 500 条短事务提交。全部表完成前不消费 manifest；若中途失败，
        # 重跑会因已处理行不再匹配 after 指纹而安全跳过，并最终标记 partial。
        table_order = [table for table in BUSINESS_TABLES if table in grouped]
        table_order.extend(sorted(set(grouped) - set(table_order)))
        for table in table_order:
            (
                table_deleted,
                table_restored,
                table_manifest_skips,
                table_verification_skips,
            ) = await _clean_candidate_table(conn, table, grouped[table])
            deleted[table] = table_deleted
            restored[table] = table_restored
            manifest_skips += table_manifest_skips
            verification_skips += table_verification_skips
            print(
                f"  {table}: 已删除 {table_deleted}，恢复 {table_restored}，"
                f"复核跳过 {table_verification_skips}",
                flush=True,
            )

        if selection.run_ids:
            status = "cleaned" if manifest_skips == 0 else "clean_partial"
            detail = (
                None
                if manifest_skips == 0
                else f"清理时有 {manifest_skips} 条 manifest 记录链已被改写或无法安全恢复"
            )
            async with conn.transaction():
                await conn.execute(
                    f"""
                    UPDATE {METADATA_TABLE}
                    SET status = $2, cleaned_at = NOW(), error = $3
                    WHERE run_id = ANY($1::uuid[]) AND status = 'complete'
                    """,
                    list(selection.run_ids),
                    status,
                    detail,
                )

    after = await _table_totals(conn, BUSINESS_TABLES)

    mode = "执行清理" if apply else "DRY-RUN（未删除）"
    print(mode)
    print("每表清理前后数量：")
    for table in BUSINESS_TABLES:
        planned = len(grouped.get(table, ()))
        note = ""
        if (
            not planned
            and not has_manifests
            and table in LOGICAL_KEYS
            and table not in STRONG_EVIDENCE_SQL
        ):
            note = "；历史无标记，不可安全识别"
        elif table not in LOGICAL_KEYS:
            note = "；seed 不写入此表"
        print(
            f"  {table}: {before[table]} -> {after[table]} "
            f"(识别 {planned}, 删除 {deleted.get(table, 0)}, "
            f"恢复 {restored.get(table, 0)}{note})"
        )
    print(
        f"合计识别 {len(candidates)}，"
        f"实际删除 {sum(deleted.values())}，"
        f"恢复 seed 前记录 {sum(restored.values())}，"
        f"复核跳过 {verification_skips}"
    )
    if apply and selection.run_ids:
        status = "cleaned" if manifest_skips == 0 else "clean_partial"
        print(
            f"已消费 manifest {len(selection.run_ids)} 次运行，"
            f"状态 {status}，跳过 {manifest_skips} 条记录链"
        )


async def _async_main(args: argparse.Namespace) -> None:
    pool = await get_pool()
    try:
        async with pool.acquire() as conn:
            if args.command == "audit":
                await audit(conn)
            elif args.command == "clean":
                await clean(conn, apply=args.apply)
            elif args.command == "legacy-audit":
                await legacy_audit(conn, args.target_date, args.recipe)
            elif args.command == "legacy-clean":
                await legacy_clean(
                    conn,
                    args.target_date,
                    apply=args.apply,
                    recipe=args.recipe,
                )
            else:
                raise ValueError(f"未知命令: {args.command}")
    finally:
        await close_pool()


def _strict_iso_date(value: str) -> date:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise argparse.ArgumentTypeError("日期必须使用严格 ISO 格式 YYYY-MM-DD")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"无效日期: {value}") from exc
    if parsed.isoformat() != value:
        raise argparse.ArgumentTypeError("日期必须使用严格 ISO 格式 YYYY-MM-DD")
    return parsed


def _add_required_legacy_date(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--date",
        dest="target_date",
        required=True,
        type=_strict_iso_date,
        help="legacy seed 执行日期（严格 YYYY-MM-DD）",
    )
    parser.add_argument(
        "--recipe",
        choices=[LEGACY_RECIPE_VERSION],
        default=LEGACY_RECIPE_VERSION,
        help="冻结的历史 seed 配方版本",
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="审计或保守清理 tradeck mock 数据")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("audit", help="统计当前可明确识别的 mock 记录")
    clean_parser = subparsers.add_parser("clean", help="清理可证明为 mock 的记录")
    clean_parser.add_argument(
        "--apply",
        action="store_true",
        help="实际执行；不传时仅 dry-run",
    )
    legacy_audit_parser = subparsers.add_parser(
        "legacy-audit",
        help="按指定日期重放旧版 seed 并精确审计",
    )
    _add_required_legacy_date(legacy_audit_parser)
    legacy_clean_parser = subparsers.add_parser(
        "legacy-clean",
        help="按指定日期保守清理精确匹配的旧版 seed",
    )
    _add_required_legacy_date(legacy_clean_parser)
    legacy_clean_parser.add_argument(
        "--apply",
        action="store_true",
        help="实际执行；不传时仅 dry-run",
    )
    return parser


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    asyncio.run(_async_main(_parser().parse_args()))


if __name__ == "__main__":
    main()
