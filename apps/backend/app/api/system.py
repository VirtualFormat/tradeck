"""系统数据任务 API：状态快照、数据表概览与手动同步。"""
from __future__ import annotations

import asyncio
import secrets
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from time import monotonic
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Response, status

from app.config import settings
from app.db import get_pool
from app.jobs import progress
from app.jobs.registry import (
    get_job_definition,
    is_job_active,
    job_catalog,
    launch_registered_job,
)
from app.scheduler import scheduler_jobs_snapshot

router = APIRouter()

_STATS_TTL_SECONDS = 60
_stats_lock = asyncio.Lock()
_stats_cache: tuple[float, list[dict], list[dict], dict[str, list[dict]]] | None = None


@dataclass(frozen=True)
class TableFreshnessRule:
    column: str | None
    kind: str | None
    max_age: timedelta | None
    label: str


# 仅允许已知业务表和固定时间列进入 SQL，禁止将请求参数用于标识符。
_TABLE_RULES: dict[str, TableFreshnessRule] = {
    "daily_prices": TableFreshnessRule("date", "date", timedelta(days=4), "最新交易日"),
    "quote_snapshots": TableFreshnessRule("updated_at", "datetime", timedelta(hours=36), "报价写入时间"),
    "index_prices": TableFreshnessRule("date", "date", timedelta(days=4), "最新交易日"),
    "movers_cache": TableFreshnessRule("snapshot_date", "date", timedelta(days=4), "榜单快照日"),
    "news_articles": TableFreshnessRule("fetched_at", "datetime", timedelta(hours=36), "新闻抓取时间"),
    "macro_indicators": TableFreshnessRule("date", "date", timedelta(days=45), "指标发布日期"),
    "income_statements": TableFreshnessRule(None, None, None, "缺少写入时间列"),
    "equity_profiles": TableFreshnessRule("updated_at", "datetime", timedelta(days=10), "资料更新时间"),
    "fundamental_metrics": TableFreshnessRule("updated_at", "datetime", timedelta(days=10), "指标更新时间"),
    "board_heat": TableFreshnessRule("updated_at", "datetime", timedelta(hours=36), "板块更新时间"),
    "symbol_board_map": TableFreshnessRule(None, None, None, "缺少写入时间列"),
    "board_sentiment": TableFreshnessRule("updated_at", "datetime", timedelta(hours=36), "舆情更新时间"),
    "fund_flow": TableFreshnessRule("updated_at", "datetime", timedelta(hours=36), "资金流更新时间"),
    "analyst_consensus": TableFreshnessRule("fetched_at", "datetime", timedelta(days=4), "共识抓取时间"),
    "balance_sheets": TableFreshnessRule("fetched_at", "datetime", timedelta(days=10), "报表抓取时间"),
    "cash_flow_statements": TableFreshnessRule("fetched_at", "datetime", timedelta(days=10), "报表抓取时间"),
    "earnings_calendar": TableFreshnessRule("fetched_at", "datetime", timedelta(days=4), "日历抓取时间"),
    "economic_calendar": TableFreshnessRule("fetched_at", "datetime", timedelta(days=4), "日历抓取时间"),
    "technical_indicators": TableFreshnessRule("computed_at", "datetime", timedelta(days=4), "指标计算时间"),
    "announcements": TableFreshnessRule("fetched_at", "datetime", timedelta(days=4), "公告抓取时间"),
    "research_reports": TableFreshnessRule("fetched_at", "datetime", timedelta(days=10), "研报抓取时间"),
    "market_breadth": TableFreshnessRule("fetched_at", "datetime", timedelta(days=4), "宽度计算时间"),
    "macro_asset_prices": TableFreshnessRule("date", "date", timedelta(days=4), "最新交易日"),
    "yield_curve_rates": TableFreshnessRule("fetched_at", "datetime", timedelta(days=4), "曲线抓取时间"),
}

def _probe_sql(
    *, key: str, name: str, table: str, where: str, rule: TableFreshnessRule
) -> str:
    key_literal = key.replace("'", "''")
    name_literal = name.replace("'", "''")
    date_expr = "NULL::date"
    datetime_expr = "NULL::timestamptz"
    if rule.column and rule.kind == "date":
        date_expr = (
            f"(SELECT {rule.column} FROM {table} WHERE ({where}) "
            f"AND {rule.column} IS NOT NULL ORDER BY {rule.column} DESC LIMIT 1)::date"
        )
    elif rule.column and rule.kind == "datetime":
        datetime_expr = (
            f"(SELECT {rule.column} FROM {table} WHERE ({where}) "
            f"AND {rule.column} IS NOT NULL ORDER BY {rule.column} DESC LIMIT 1)::timestamptz"
        )
    return (
        f"SELECT '{key_literal}' AS probe_key, '{name_literal}' AS probe_name, "
        f"EXISTS(SELECT 1 FROM {table} WHERE {where}) AS has_rows, "
        f"{date_expr} AS latest_data_date, {datetime_expr} AS latest_data_at"
    )


_TABLE_PROBE_SQL = " UNION ALL ".join(
    _probe_sql(key=table, name=table, table=table, where="TRUE", rule=rule)
    for table, rule in _TABLE_RULES.items()
)


def _freshness_payload(
    *,
    name: str,
    rule: TableFreshnessRule,
    has_rows: bool,
    latest_data_date: date | None,
    latest_data_at: datetime | None,
    now: datetime,
) -> dict:
    if not has_rows:
        return {
            "name": name,
            "status": "empty",
            "latest_data_at": None,
            "latest_data_date": None,
            "note": "暂无数据",
        }
    if rule.column is None or rule.max_age is None:
        return {
            "name": name,
            "status": "unknown",
            "latest_data_at": None,
            "latest_data_date": None,
            "note": rule.label,
        }
    if latest_data_at is None and latest_data_date is None:
        return {
            "name": name,
            "status": "unknown",
            "latest_data_at": None,
            "latest_data_date": None,
            "note": f"{rule.label}为空，无法判断新鲜度",
        }
    if latest_data_at is not None:
        latest_data_at = (
            latest_data_at.astimezone(timezone.utc)
            if latest_data_at.tzinfo
            else latest_data_at.replace(tzinfo=timezone.utc)
        )
        age = max(now - latest_data_at, timedelta(0))
    else:
        age = max(now.date() - latest_data_date, timedelta(0))
    max_hours = int(rule.max_age.total_seconds() // 3600)
    if age <= rule.max_age:
        health_status = "fresh"
        note = f"{rule.label}在 {max_hours} 小时阈值内"
    else:
        health_status = "stale"
        age_hours = int(age.total_seconds() // 3600)
        note = f"{rule.label}距今约 {age_hours} 小时，超过 {max_hours} 小时阈值"
    return {
        "name": name,
        "status": health_status,
        "latest_data_at": latest_data_at.isoformat() if latest_data_at else None,
        "latest_data_date": latest_data_date.isoformat() if latest_data_date else None,
        "note": note,
    }


def _aggregate_data_health(table_rows: list[dict]) -> dict:
    if not table_rows:
        return {
            "status": "unknown",
            "latest_data_at": None,
            "latest_data_date": None,
            "note": "未配置数据健康检查",
            "tables": [],
        }
    statuses = {row["status"] for row in table_rows}
    health_status = next(iter(statuses)) if len(statuses) == 1 else "partial"
    abnormal = [row for row in table_rows if row["status"] != "fresh"]
    if health_status == "fresh":
        note = "全部关联数据正常"
    elif health_status == "partial":
        note = "数据分项状态不一致：" + "、".join(
            f"{row['name']}（{row['status']}）" for row in table_rows
        )
    elif len(table_rows) == 1:
        note = table_rows[0]["note"]
    else:
        note = "；".join(f"{row['name']}：{row['note']}" for row in table_rows)
    return {
        "status": health_status,
        "latest_data_at": max(
            (row["latest_data_at"] for row in table_rows if row["latest_data_at"]),
            default=None,
        ),
        "latest_data_date": max(
            (
                row["latest_data_date"]
                for row in table_rows
                if row["latest_data_date"]
            ),
            default=None,
        ),
        "note": note,
        "tables": table_rows,
    }


def _effective_job_status(
    *, active: bool, latest: dict | None, data_health: dict, maintenance: bool
) -> str:
    if active or (latest and latest["status"] == "running"):
        return "running"
    if latest and latest["status"] == "error":
        return "error"
    if latest and latest["status"] in {"empty", "partial"}:
        return latest["status"]
    if maintenance:
        return latest["status"] if latest else "idle"
    health_status = data_health["status"]
    if health_status in {"partial", "empty", "stale"}:
        return health_status
    if health_status == "fresh":
        return "done"
    return latest["status"] if latest else "idle"


def _job_probe_plan(
    catalog: list[dict],
) -> tuple[str | None, dict[str, tuple[str, TableFreshnessRule]]]:
    statements: list[str] = []
    metadata: dict[str, tuple[str, TableFreshnessRule]] = {}
    for job in catalog:
        for index, query in enumerate(job.get("health_queries", [])):
            table = query["table"]
            if table not in _TABLE_RULES:
                continue
            base = _TABLE_RULES[table]
            column = query.get("latest_column") or base.column
            kind = query.get("latest_kind") or base.kind
            max_age_hours = query.get("max_age_hours")
            max_age = (
                timedelta(hours=max_age_hours)
                if max_age_hours is not None
                else base.max_age
            )
            rule = TableFreshnessRule(
                column,
                kind,
                max_age,
                query.get("label") or base.label,
            )
            key = f"{job['id']}:{index}"
            name = query.get("name") or table
            statements.append(
                _probe_sql(
                    key=key,
                    name=name,
                    table=table,
                    where=query.get("where") or "TRUE",
                    rule=rule,
                )
            )
            metadata[key] = (job["id"], rule)
    return (" UNION ALL ".join(statements) or None), metadata


async def _get_database_stats(
    catalog: list[dict],
) -> tuple[list[dict], list[dict], dict[str, list[dict]]]:
    """缓存较重的库表统计，避免前端短轮询反复扫描 daily_prices。"""
    global _stats_cache

    now = monotonic()
    if _stats_cache and now - _stats_cache[0] < _STATS_TTL_SECONDS:
        return _stats_cache[1], _stats_cache[2], _stats_cache[3]

    async with _stats_lock:
        now = monotonic()
        if _stats_cache and now - _stats_cache[0] < _STATS_TTL_SECONDS:
            return _stats_cache[1], _stats_cache[2], _stats_cache[3]

        job_probe_sql, job_probe_metadata = _job_probe_plan(catalog)
        pool = await get_pool()
        async with pool.acquire() as conn:
            tables = await conn.fetch(
                """
                SELECT relname AS table_name,
                       n_live_tup::bigint AS row_count,
                       pg_total_relation_size(
                         format('%I.%I', schemaname, relname)::regclass
                       )
                         AS total_bytes
                FROM pg_stat_user_tables
                WHERE schemaname = 'public'
                  AND relname = ANY($1::text[])
                ORDER BY relname
                """,
                list(_TABLE_RULES),
            )
            freshness_rows = await conn.fetch(_TABLE_PROBE_SQL)
            job_probe_rows = (
                await conn.fetch(job_probe_sql) if job_probe_sql is not None else []
            )
            daily_markets = await conn.fetch(
                """
                SELECT market, count(*)::bigint AS row_count, max(date) AS latest_date
                FROM daily_prices
                GROUP BY market
                ORDER BY market
                """
            )

        stats_by_table = {row["table_name"]: row for row in tables}
        freshness_by_table = {row["probe_key"]: row for row in freshness_rows}
        checked_at = datetime.now(timezone.utc)
        table_rows = []
        for table in _TABLE_RULES:
            row = stats_by_table.get(table)
            row_count = int(row["row_count"] or 0) if row else 0
            probe = freshness_by_table[table]
            health = _freshness_payload(
                name=table,
                rule=_TABLE_RULES[table],
                has_rows=probe["has_rows"],
                latest_data_date=probe["latest_data_date"],
                latest_data_at=probe["latest_data_at"],
                now=checked_at,
            )
            table_rows.append(
                {
                    "name": table,
                    "row_count": row_count,
                    "total_bytes": int(row["total_bytes"] or 0) if row else 0,
                    "latest_data_at": health["latest_data_at"],
                    "latest_data_date": health["latest_data_date"],
                    "freshness": health["status"],
                    "freshness_note": health["note"],
                }
            )
        job_health_rows: dict[str, list[dict]] = {}
        for probe in job_probe_rows:
            job_id, rule = job_probe_metadata[probe["probe_key"]]
            job_health_rows.setdefault(job_id, []).append(
                _freshness_payload(
                    name=probe["probe_name"],
                    rule=rule,
                    has_rows=probe["has_rows"],
                    latest_data_date=probe["latest_data_date"],
                    latest_data_at=probe["latest_data_at"],
                    now=checked_at,
                )
            )
        market_rows = [
            {
                "market": row["market"],
                "row_count": int(row["row_count"] or 0),
                "latest_date": row["latest_date"].isoformat()
                if row["latest_date"]
                else None,
            }
            for row in daily_markets
        ]
        _stats_cache = (now, table_rows, market_rows, job_health_rows)
        return table_rows, market_rows, job_health_rows


@router.get("/api/system/jobs")
async def get_system_jobs():
    """最近的任务运行记录（含空结果、部分结果与异常），新的在前。"""
    return progress.snapshot()


@router.get("/api/system/data")
async def get_system_data():
    """数据页聚合快照：任务目录、运行状态、下次调度与 24 张表统计。"""
    catalog = job_catalog()
    schedules = scheduler_jobs_snapshot()
    runs = progress.snapshot(limit=100)

    latest_runs: dict[str, dict] = {}
    for run in runs:
        latest_runs.setdefault(run["job"], run)

    table_rows, market_rows, filtered_health = await _get_database_stats(catalog)
    tables_by_name = {row["name"]: row for row in table_rows}

    jobs = []
    for job in catalog:
        latest = latest_runs.get(job["id"])
        active = is_job_active(job["id"])
        related_tables = filtered_health.get(job["id"])
        if related_tables is None:
            related_tables = [
                {
                    "name": name,
                    "status": tables_by_name[name]["freshness"],
                    "latest_data_at": tables_by_name[name]["latest_data_at"],
                    "latest_data_date": tables_by_name[name]["latest_data_date"],
                    "note": tables_by_name[name]["freshness_note"],
                }
                for name in job["tables"]
                if name in tables_by_name
            ]
        data_health = _aggregate_data_health(related_tables)
        jobs.append(
            {
                **{key: value for key, value in job.items() if key != "health_queries"},
                "status": _effective_job_status(
                    active=active,
                    latest=latest,
                    data_health=data_health,
                    maintenance=job.get("maintenance", False),
                ),
                "data_health": data_health,
                "last_run": latest
                if not active or (latest and latest["status"] == "running")
                else None,
                "next_run_at": schedules.get(job["id"], {}).get("next_run_at"),
            }
        )

    return {
        "jobs": jobs,
        "tables": table_rows,
        "daily_markets": market_rows,
        "summary": {
            "job_count": len(jobs),
            "running_count": sum(1 for job in jobs if job["status"] == "running"),
            "error_count": sum(1 for job in jobs if job["status"] == "error"),
            "empty_count": sum(1 for job in jobs if job["status"] == "empty"),
            "partial_count": sum(1 for job in jobs if job["status"] == "partial"),
            "stale_count": sum(1 for job in jobs if job["status"] == "stale"),
            "table_count": len(table_rows),
            "total_rows": sum(row["row_count"] for row in table_rows),
            "total_bytes": sum(row["total_bytes"] for row in table_rows),
        },
    }


@router.post("/api/system/jobs/{job_id}/run", status_code=status.HTTP_202_ACCEPTED)
async def run_system_job(
    job_id: str,
    response: Response,
    x_data_sync_token: Annotated[str | None, Header()] = None,
):
    """后台触发一次白名单数据任务；运行中任务不重复触发。"""
    if not settings.DATA_SYNC_TOKEN:
        raise HTTPException(status_code=503, detail="手动同步未配置")
    if not x_data_sync_token or not secrets.compare_digest(
        x_data_sync_token, settings.DATA_SYNC_TOKEN
    ):
        raise HTTPException(status_code=401, detail="无权触发同步任务")
    job = get_job_definition(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    if not job.allow_manual:
        raise HTTPException(status_code=403, detail="该任务不支持手动同步")
    if is_job_active(job_id):
        response.status_code = status.HTTP_409_CONFLICT
        return {"accepted": False, "job": job_id, "message": "任务正在运行"}
    if not launch_registered_job(job_id):
        response.status_code = status.HTTP_409_CONFLICT
        return {"accepted": False, "job": job_id, "message": "任务未触发"}
    return {"accepted": True, "job": job_id, "message": "同步任务已启动"}
