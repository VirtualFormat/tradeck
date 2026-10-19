"""进程内配额：滑动窗口计数（docs/MCP.md「配额」）。

- 每令牌调用：全部工具合计 MCP_RATE_PER_MINUTE 次/60 秒。
- 每用户回测提交：MCP_BACKTESTS_PER_HOUR 次/3600 秒（按提交尝试计，quant 拒绝也算）。

单进程纪律：计数在进程内存，多 worker 会让配额按 worker 数放大（Dockerfile 固定 --workers 1）。
并发安全：仅在事件循环内同步调用（无 await 点），天然串行。
"""

from __future__ import annotations

import math
import time
from collections import deque
from collections.abc import Callable


class SlidingWindowLimiter:
    """滑动窗口限流：窗口内命中数达到上限即拒绝，并给出最早可重试的秒数。"""

    def __init__(
        self,
        limit: int,
        window_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.limit = limit
        self.window = window_seconds
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}

    def hit(self, key: str) -> float | None:
        """登记一次命中；未超限返回 None，超限不登记并返回需等待的秒数。"""
        now = self._clock()
        q = self._hits.get(key)
        if q is None:
            q = self._hits[key] = deque()
        while q and q[0] <= now - self.window:
            q.popleft()
        if len(q) >= self.limit:
            return max(q[0] + self.window - now, 0.0)
        q.append(now)
        self._gc(now)
        return None

    def _gc(self, now: float) -> None:
        """键数膨胀时清掉窗口已空的键（防大量一次性令牌把字典撑大）。"""
        if len(self._hits) < 1024:
            return
        for k in [
            k for k, q in self._hits.items() if not q or q[-1] <= now - self.window
        ]:
            del self._hits[k]


def retry_hint(seconds: float) -> str:
    """等待时长 → 中文提示（秒级向上取整，超过 2 分钟按分钟）。"""
    secs = max(1, math.ceil(seconds))
    if secs < 120:
        return f"{secs} 秒"
    return f"{math.ceil(secs / 60)} 分钟"
