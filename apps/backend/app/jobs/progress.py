"""任务进度注册表（进程内存）：job 上报，/api/system/jobs 读取，前端轮询展示。

全量初始化 / 每日增量更新共用同一通道。重启即清空，只保留最近 20 条。
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone

_lock = threading.Lock()
_runs: list[dict] = []
_MAX = 20


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def job_start(job: str, label: str, total: int, note: str = "") -> None:
    with _lock:
        _runs.insert(
            0,
            {
                "job": job,
                "label": label,
                "status": "running",
                "processed": 0,
                "total": total,
                "percent": 0.0,
                "note": note,
                "started_at": _now(),
                "finished_at": None,
            },
        )
        del _runs[_MAX:]


def job_update(job: str, processed: int) -> None:
    with _lock:
        for r in _runs:
            if r["job"] == job and r["status"] == "running":
                r["processed"] = processed
                r["percent"] = (
                    round(processed / r["total"] * 100, 1) if r["total"] else 0.0
                )
                return


def job_done(job: str, note: str = "") -> None:
    _finish(job, "done", note)


def job_error(job: str, note: str) -> None:
    _finish(job, "error", note)


def is_running(job: str) -> bool:
    with _lock:
        return any(r["job"] == job and r["status"] == "running" for r in _runs)


def _finish(job: str, status: str, note: str) -> None:
    with _lock:
        for r in _runs:
            if r["job"] == job and r["status"] == "running":
                r["status"] = status
                r["finished_at"] = _now()
                if note:
                    r["note"] = note
                return


def snapshot(limit: int = 10) -> list[dict]:
    """最近的任务运行记录（新的在前）。"""
    with _lock:
        return [dict(r) for r in _runs[:limit]]
