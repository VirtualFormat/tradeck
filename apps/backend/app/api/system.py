"""GET /api/system/jobs — 任务进度快照（内存注册表，前端轮询展示）"""
from __future__ import annotations

from fastapi import APIRouter

from app.jobs import progress

router = APIRouter()


@router.get("/api/system/jobs")
async def get_system_jobs():
    """最近的任务运行记录（running/done/error + 进度），新的在前。"""
    return progress.snapshot()
