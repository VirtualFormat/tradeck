"""collector 运维 API：任务状态快照（含调度信息）与手动触发。

/api/system/jobs 在进程内 job 运行记录上合并 scheduler 的 next_run_at，
供 data-api 的 /api/system/data 与前端同步状态条消费。
库表扫描统计（/api/system/data 的完整版）保留在 data-api/backend 侧。
"""
from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Response, status

from app.config import settings
from app.jobs import progress
from app.jobs.registry import (
    get_job_definition,
    is_job_active,
    launch_registered_job,
)
from app.scheduler import scheduler_jobs_snapshot

router = APIRouter()


@router.get("/api/system/jobs")
async def get_system_jobs():
    """最近的任务运行记录（含空结果、部分结果与异常），新的在前。"""
    return progress.snapshot()


@router.get("/api/system/schedules")
async def get_system_schedules():
    """各任务的调度信息（下次运行时间）；scheduler 未启动时返回空表。"""
    return scheduler_jobs_snapshot()


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
