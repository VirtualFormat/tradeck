"""任务进度注册表（进程内存）：job 上报，/api/system/jobs 读取，前端轮询展示。

全量初始化 / 每日增量更新共用同一通道。重启即清空，只保留最近 100 条。
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Literal

JobStatus = Literal["running", "done", "empty", "partial", "error"]
_FINISHED_STATUSES = {"done", "empty", "partial", "error"}

_lock = threading.Lock()
_runs: list[dict] = []
_MAX = 100


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def job_start(
    job: str,
    label: str,
    total: int,
    note: str = "",
    trigger: str = "schedule",
) -> str:
    started_at = _now()
    with _lock:
        _runs.insert(
            0,
            {
                "job": job,
                "label": label,
                "trigger": trigger,
                "status": "running",
                "processed": 0,
                "total": total,
                "percent": 0.0,
                "note": note,
                "started_at": started_at,
                "finished_at": None,
            },
        )
        del _runs[_MAX:]
    return started_at


def job_set_total(job: str, total: int, started_at: str | None = None) -> None:
    """任务启动后补充总量（日 K 需先请求 universe 才能确定）。"""
    with _lock:
        for r in _runs:
            if (
                r["job"] == job
                and r["status"] == "running"
                and (started_at is None or r["started_at"] == started_at)
            ):
                r["total"] = total
                r["percent"] = (
                    round(r["processed"] / total * 100, 1) if total else 0.0
                )
                return


def job_update(job: str, processed: int, started_at: str | None = None) -> None:
    with _lock:
        for r in _runs:
            if (
                r["job"] == job
                and r["status"] == "running"
                and (started_at is None or r["started_at"] == started_at)
            ):
                r["processed"] = processed
                r["percent"] = (
                    round(processed / r["total"] * 100, 1) if r["total"] else 0.0
                )
                return


def job_done(job: str, note: str = "", started_at: str | None = None) -> None:
    _finish(job, "done", note, started_at)


def job_empty(job: str, note: str = "", started_at: str | None = None) -> None:
    _finish(job, "empty", note or "处理 0 行，未获取到新数据", started_at)


def job_partial(job: str, note: str = "", started_at: str | None = None) -> None:
    _finish(job, "partial", note or "仅获取到部分数据", started_at)


def job_error(job: str, note: str, started_at: str | None = None) -> None:
    _finish(job, "error", note, started_at)


def job_reclassify(
    job: str,
    status: JobStatus,
    note: str = "",
    started_at: str | None = None,
) -> None:
    """重分类最近一次已结束记录，供自带进度上报的任务补充结果语义。"""
    if status == "running":
        return
    with _lock:
        for run in _runs:
            if (
                run["job"] == job
                and run["status"] in _FINISHED_STATUSES
                and (started_at is None or run["started_at"] == started_at)
            ):
                run["status"] = status
                if note:
                    run["note"] = note
                return


def is_running(job: str) -> bool:
    with _lock:
        return any(r["job"] == job and r["status"] == "running" for r in _runs)


def _finish(
    job: str, status: JobStatus, note: str, started_at: str | None = None
) -> None:
    if status == "running":
        raise ValueError("running 不是任务终态")
    with _lock:
        for r in _runs:
            if (
                r["job"] == job
                and r["status"] == "running"
                and (started_at is None or r["started_at"] == started_at)
            ):
                r["status"] = status
                r["finished_at"] = _now()
                if status == "done":
                    if not r["total"]:
                        r["total"] = 1
                    r["processed"] = r["total"]
                    r["percent"] = 100.0
                elif status in {"empty", "partial"}:
                    # 任务已结束，100% 表示执行过程完成，不代表写入量达标。
                    r["percent"] = 100.0
                if note:
                    r["note"] = note
                return


def snapshot(limit: int = 50) -> list[dict]:
    """最近的任务运行记录（新的在前）。"""
    with _lock:
        return [dict(r) for r in _runs[:limit]]
