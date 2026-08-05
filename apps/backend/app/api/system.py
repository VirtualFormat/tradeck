"""系统数据任务 API：状态快照、数据表概览与手动同步。"""
from __future__ import annotations

import asyncio
import secrets
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

_STATS_TTL_SECONDS = 300
_stats_lock = asyncio.Lock()
_stats_cache: tuple[float, list[dict], list[dict]] | None = None


async def _get_database_stats() -> tuple[list[dict], list[dict]]:
    """缓存较重的库表统计，避免前端短轮询反复扫描 daily_prices。"""
    global _stats_cache

    now = monotonic()
    if _stats_cache and now - _stats_cache[0] < _STATS_TTL_SECONDS:
        return _stats_cache[1], _stats_cache[2]

    async with _stats_lock:
        now = monotonic()
        if _stats_cache and now - _stats_cache[0] < _STATS_TTL_SECONDS:
            return _stats_cache[1], _stats_cache[2]

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
                ORDER BY relname
                """
            )
            daily_markets = await conn.fetch(
                """
                SELECT market, count(*)::bigint AS row_count, max(date) AS latest_date
                FROM daily_prices
                GROUP BY market
                ORDER BY market
                """
            )

        table_rows = [
            {
                "name": row["table_name"],
                "row_count": int(row["row_count"] or 0),
                "total_bytes": int(row["total_bytes"] or 0),
            }
            for row in tables
        ]
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
        _stats_cache = (now, table_rows, market_rows)
        return table_rows, market_rows


@router.get("/api/system/jobs")
async def get_system_jobs():
    """最近的任务运行记录（running/done/error + 进度），新的在前。"""
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

    jobs = []
    for job in catalog:
        latest = latest_runs.get(job["id"])
        active = is_job_active(job["id"])
        jobs.append(
            {
                **job,
                "status": "running"
                if active
                else (latest["status"] if latest else "idle"),
                "last_run": latest
                if not active or (latest and latest["status"] == "running")
                else None,
                "next_run_at": schedules.get(job["id"], {}).get("next_run_at"),
            }
        )

    table_rows, market_rows = await _get_database_stats()

    return {
        "jobs": jobs,
        "tables": table_rows,
        "daily_markets": market_rows,
        "summary": {
            "job_count": len(jobs),
            "running_count": sum(1 for job in jobs if job["status"] == "running"),
            "error_count": sum(1 for job in jobs if job["status"] == "error"),
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
