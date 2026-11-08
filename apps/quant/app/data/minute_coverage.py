"""分钟缓存覆盖账本与文件锁：账本嵌入 Parquet 元数据，与数据一次原子发布。"""

from __future__ import annotations

import asyncio
import fcntl
import json
import time
from contextlib import asynccontextmanager, contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

_METADATA_KEY = b"tradeck.minute.coverage.v1"
_LOCK_TIMEOUT_SECONDS = 180.0


def utc_today() -> date:
    """账本有效期按 UTC 日期计算，与服务器日期窗口的交易所时区分开。"""
    return datetime.now(timezone.utc).date()


def decode_coverage(metadata: dict[bytes, bytes], year: int) -> set[date]:
    """旧缓存/坏账本无已验证覆盖；空结果覆盖仅在当天有效。"""
    payload = json.loads(metadata.get(_METADATA_KEY, b"{}"))
    if not isinstance(payload, dict):
        raise ValueError("分钟覆盖账本格式非法")
    days = payload.get("days", [])
    empty = payload.get("empty_days", {})
    if not isinstance(days, list) or not isinstance(empty, dict):
        raise ValueError("分钟覆盖账本日期格式非法")
    permanent = {date.fromisoformat(day) for day in days}
    permanent.update(
        date.fromisoformat(day)
        for day, verified_on in empty.items()
        if verified_on == utc_today().isoformat()
    )
    if any(day.year != year for day in permanent):
        raise ValueError("分钟覆盖账本年份不符")
    return permanent


def encode_coverage(days: set[date], empty_days: set[date]) -> dict[bytes, bytes]:
    """成功读到的空日期作一天负缓存，防服务端静默空降级永久遮蔽后续数据。"""
    payload = {
        "days": sorted(day.isoformat() for day in days - empty_days),
        "empty_days": {
            day.isoformat(): utc_today().isoformat() for day in sorted(empty_days)
        },
    }
    return {_METADATA_KEY: json.dumps(payload).encode()}


def dates(start: date, end: date) -> Iterator[date]:
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def missing_ranges(
    covered: set[date], start: date, end: date
) -> list[tuple[date, date]]:
    """逐自然日检查已验证覆盖，合并相邻缺口。"""
    ranges: list[tuple[date, date]] = []
    for day in dates(start, end):
        if day in covered:
            continue
        if ranges and day == ranges[-1][1] + timedelta(days=1):
            ranges[-1] = (ranges[-1][0], day)
        else:
            ranges.append((day, day))
    return ranges


@asynccontextmanager
async def locked_cache(path: Path):
    """非阻塞轮询 flock，跨协程/线程/进程串行同一年文件的读改写。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(".lock").open("a+b") as lock:
        async with asyncio.timeout(_LOCK_TIMEOUT_SECONDS):
            while True:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    await asyncio.sleep(0.05)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


@contextmanager
def locked_cache_sync(path: Path):
    """独立 save_minute 调用使用同一文件锁。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(".lock").open("a+b") as lock:
        deadline = time.monotonic() + _LOCK_TIMEOUT_SECONDS
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("等待分钟缓存文件锁超时")
                time.sleep(0.05)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
