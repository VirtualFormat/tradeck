"""数据质量层的数据模型：处置三态、严重级、单行的质量结论。

三态处置（Disposition）：
- ACCEPT  合格，写库
- REPAIR  可自动修（类型/日期/symbol 归一），修后写库
- REJECT  物理不可能/明显损坏，拦截 + 落 quarantine 表

严重级（Severity）：
- P0 物理不可能（OHLC 不自洽、负价、缺必要字段）→ REJECT
- P1 明显损坏（涨跌幅越物理边界）→ REJECT + warn
- P2 可疑但放行（统计异常/跳空）→ ACCEPT + 标记（不拦，供量化侧自决）
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class Disposition(str, Enum):
    ACCEPT = "accept"
    REPAIR = "repair"
    REJECT = "reject"


class Severity(str, Enum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"


@dataclass
class RejectRecord:
    """一条被拦截（或 P2 标记）的记录，落 quarantine 表留痕。"""

    source_table: str
    symbol: str | None
    raw_payload: dict[str, Any]
    reject_reason: str
    severity: Severity
    # P2 是「放行但标记」，rejected_at 仍记录以备审计
    rejected_at: datetime | None = None


@dataclass
class QualityOutcome:
    """一批行的质量闸结果。"""

    accepted: list[dict[str, Any]] = field(default_factory=list)
    rejects: list[RejectRecord] = field(default_factory=list)
    repaired_count: int = 0
    total: int = 0

    @property
    def rejected_count(self) -> int:
        # 只统计真正拦截的（P0/P1），P2 标记不计入拒绝数
        return sum(1 for r in self.rejects if r.severity in (Severity.P0, Severity.P1))

    @property
    def quality_score(self) -> float:
        """质量分 = 合格数 / 总数（REPAIR 视为合格），0-1。"""
        if self.total == 0:
            return 1.0
        return round((self.total - self.rejected_count) / self.total, 4)
