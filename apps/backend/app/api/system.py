"""系统数据 API（data-api 侧）：仅保留库表扫描概览 /api/system/data。

拆分后职责划分：
- /api/system/data 留在 data-api——纯库表统计（24 张表行数/体积/新鲜度、
  daily_prices 市场覆盖），不依赖任何进程内调度状态。
- /api/system/jobs 与手动触发 /run 已归位 collector（唯一写者持有
  scheduler / registry / progress，见 apps/data-collector/app/api/system.py）。
- next_run_at：data-api 进程内没有 scheduler，改为向 collector 的
  /api/system/schedules 发起 HTTP 查询；last_run 同理来自 collector 的
  /api/system/jobs。collector 不可达（mock 模式无 collector、或尚未
  启动）时优雅降级为 null，绝不因此报错。
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from time import monotonic

import httpx
from fastapi import APIRouter

from app.config import settings
from app.db import get_pool

logger = logging.getLogger(__name__)

router = APIRouter()

# 任务展示元数据（展示名 + cron 文案 + 关联表 + 任务专属健康查询）；
# 顺序即 /api/system/data 输出顺序。
# 与 collector 的 registry 目录静态对齐：collector 增删任务时需同步此表。
# health_queries 字段与 registry.JobHealthQuery 同构（name/table/where/...）。
_CATALOG: list[dict] = [
    {
        "id": "daily_kline",
        "label": "日 K 每日更新",
        "schedule": "A/港 08:30；美股 21:30 UTC",
        "tables": ["daily_prices", "equity_profiles"],
    },
    {
        "id": "daily_kline_full",
        "label": "日 K 全量初始化",
        "schedule": "启动时按市场缺口自动触发",
        "tables": ["daily_prices", "equity_profiles"],
    },
    {
        "id": "realtime_quotes",
        "label": "实时报价",
        "schedule": "每 30 分钟",
        "tables": ["quote_snapshots"],
        "health_queries": [
            {"name": "A 股报价", "table": "quote_snapshots", "where": "market = 'CN'"},
            {"name": "港股报价", "table": "quote_snapshots", "where": "market = 'HK'"},
            {"name": "美股报价", "table": "quote_snapshots", "where": "market = 'US'"},
        ],
    },
    {
        "id": "indices",
        "label": "指数与商品历史",
        "schedule": "各市场收盘后分批更新",
        "tables": ["index_prices"],
    },
    {
        "id": "movers",
        "label": "美股涨跌榜",
        "schedule": "每 5 分钟",
        "tables": ["movers_cache"],
        "health_queries": [
            {"name": "美股榜单", "table": "movers_cache", "where": "market = 'US'"},
        ],
    },
    {
        "id": "movers_cn",
        "label": "A 股涨跌榜",
        "schedule": "每天 09:10 UTC",
        "tables": ["movers_cache"],
        "health_queries": [
            {"name": "A 股榜单", "table": "movers_cache", "where": "market = 'CN'"},
        ],
    },
    {
        "id": "news",
        "label": "海外新闻",
        "schedule": "每 30 分钟",
        "tables": ["news_articles"],
        "health_queries": [
            {
                "name": "海外新闻",
                "table": "news_articles",
                "where": "symbol IS NOT NULL AND symbol !~ '[.](SH|SS|SZ|BJ)$'",
            },
        ],
    },
    {
        "id": "akshare_news",
        "label": "A 股新闻",
        "schedule": "每 30 分钟",
        "tables": ["news_articles"],
        "health_queries": [
            {
                "name": "A 股新闻",
                "table": "news_articles",
                "where": "symbol ~ '[.](SH|SS|SZ|BJ)$'",
            },
        ],
    },
    {
        "id": "news_score",
        "label": "新闻情绪打分",
        "schedule": "每 30 分钟",
        "tables": ["news_articles"],
        "health_queries": [
            {
                "name": "已打分新闻",
                "table": "news_articles",
                "where": "scored_at IS NOT NULL",
                "latest_column": "scored_at",
                "latest_kind": "datetime",
                "max_age_hours": 36,
                "label": "最近打分时间",
            },
        ],
    },
    {
        "id": "macro",
        "label": "宏观指标",
        "schedule": "每天 06:00 UTC",
        "tables": ["macro_indicators"],
    },
    {
        "id": "fundamentals",
        "label": "公司与财务数据",
        "schedule": "每周一 07:00 UTC",
        "tables": [
            "equity_profiles",
            "fundamental_metrics",
            "income_statements",
            "balance_sheets",
            "cash_flow_statements",
        ],
    },
    {
        "id": "analyst_consensus",
        "label": "分析师共识",
        "schedule": "每天 21:00 UTC",
        "tables": ["analyst_consensus"],
    },
    {
        "id": "earnings_calendar",
        "label": "财报日历",
        "schedule": "每天 12:00 UTC",
        "tables": ["earnings_calendar"],
    },
    {
        "id": "economic_calendar",
        "label": "宏观数据日历",
        "schedule": "每天 06:30 UTC",
        "tables": ["economic_calendar"],
    },
    {
        "id": "board_heat",
        "label": "板块行情热度",
        "schedule": "每 30 分钟",
        "tables": ["board_heat"],
    },
    {
        "id": "board_map",
        "label": "板块归属映射",
        "schedule": "每周一 08:00 UTC",
        "tables": ["symbol_board_map"],
    },
    {
        "id": "board_sentiment",
        "label": "板块舆情聚合",
        "schedule": "每 30 分钟",
        "tables": ["board_sentiment"],
    },
    {
        "id": "fund_flow",
        "label": "个股资金流向",
        "schedule": "每 5 分钟",
        "tables": ["fund_flow"],
    },
    {
        "id": "announcements",
        "label": "A 股公告",
        "schedule": "每天 10:30 UTC",
        "tables": ["announcements"],
    },
    {
        "id": "research_reports",
        "label": "A 股券商研报",
        "schedule": "每周一 09:00 UTC",
        "tables": ["research_reports"],
    },
    {
        "id": "market_breadth",
        "label": "A 股市场宽度",
        "schedule": "每 30 分钟",
        "tables": ["market_breadth"],
        "health_queries": [
            {
                "name": "A 股宽度",
                "table": "market_breadth",
                "where": "market = 'CN' AND source = 'legu'",
            },
        ],
    },
    {
        "id": "market_breadth_global",
        "label": "美港市场宽度",
        "schedule": "每天 09:05 / 22:05 UTC",
        "tables": ["market_breadth"],
        "health_queries": [
            {
                "name": "美股宽度",
                "table": "market_breadth",
                "where": "market = 'US' AND source = 'daily_kline'",
            },
            {
                "name": "港股宽度",
                "table": "market_breadth",
                "where": "market = 'HK' AND source = 'daily_kline'",
            },
        ],
    },
    {
        "id": "macro_assets",
        "label": "宏观资产与收益率曲线",
        "schedule": "每天 21:30 UTC",
        "tables": ["macro_asset_prices", "yield_curve_rates"],
    },
    {
        "id": "technical_indicators",
        "label": "技术指标",
        "schedule": "每天 09:00 / 22:00 UTC",
        "tables": ["technical_indicators"],
    },
    {
        "id": "cleanup",
        "label": "过期数据清理",
        "schedule": "每天 03:00 UTC",
        "tables": [
            "movers_cache",
            "board_heat",
            "board_sentiment",
            "fund_flow",
            "news_articles",
        ],
        "maintenance": True,
    },
]

_SCHEDULES_TTL_SECONDS = 60
_schedules_cache: tuple[float, dict[str, dict]] | None = None


async def _collector_schedules() -> dict[str, dict]:
    """从 collector 拉取各任务的调度信息；失败优雅降级为空表（next_run_at 为 null）。

    结果缓存 60 秒，避免前端短轮询把请求放大到 collector。
    """
    global _schedules_cache

    now = monotonic()
    if _schedules_cache and now - _schedules_cache[0] < _SCHEDULES_TTL_SECONDS:
        return _schedules_cache[1]

    url = f"{settings.COLLECTOR_API_URL.rstrip('/')}/api/system/schedules"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            res = await client.get(url)
            schedules = res.json() if res.status_code == 200 else {}
            if not isinstance(schedules, dict):
                schedules = {}
    except Exception:
        logger.debug("collector 调度信息查询失败（%s），next_run_at 降级为 null", url)
        return {}

    _schedules_cache = (now, schedules)
    return schedules


async def _collector_job_runs() -> list[dict]:
    """从 collector 拉取最近的任务运行记录；失败优雅降级为空列表。

    不缓存：/api/system/data 本身有 60s 统计缓存兜底，运行记录需要更实时。
    """
    url = f"{settings.COLLECTOR_API_URL.rstrip('/')}/api/system/jobs"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            res = await client.get(url)
            runs = res.json() if res.status_code == 200 else []
            return runs if isinstance(runs, list) else []
    except Exception:
        logger.debug("collector 任务记录查询失败（%s），last_run 降级为 null", url)
        return []

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


@router.get("/api/system/data")
async def get_system_data():
    """数据页聚合快照：任务目录、运行状态、下次调度与 24 张表统计。

    库表扫描在 data-api 本地完成；last_run / next_run_at 经 collector
    HTTP 聚合，collector 不可达时优雅降级为 null（不报错）。
    """
    catalog = _CATALOG
    schedules, runs = await asyncio.gather(
        _collector_schedules(), _collector_job_runs()
    )
    table_rows, market_rows, filtered_health = await _get_database_stats(catalog)
    tables_by_name = {row["name"]: row for row in table_rows}

    latest_runs: dict[str, dict] = {}
    for run in runs:
        latest_runs.setdefault(run.get("job"), run)

    jobs = []
    for job in catalog:
        latest = latest_runs.get(job["id"])
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
                for name in job.get("tables", ())
                if name in tables_by_name
            ]
        data_health = _aggregate_data_health(related_tables)
        jobs.append(
            {
                **{key: value for key, value in job.items() if key != "health_queries"},
                "status": _effective_job_status(
                    active=False,
                    latest=latest,
                    data_health=data_health,
                    maintenance=job.get("maintenance", False),
                ),
                "data_health": data_health,
                "last_run": latest,
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
