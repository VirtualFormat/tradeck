"""数据质量层（Data Quality Layer）。

collector 内介于「datasource 拉取」与「写库」之间的独立质量闸。
写库 job 统一经 `quality_gate(table, rows)` 过一道，只放合格数据入库；
被拦数据落 quarantine 表留痕，质量度量落 metrics 表可观测。

设计见 docs/TASKS-DATA-SERVICE.md 阶段三.五。
"""
from app.quality.gate import quality_gate
from app.quality.models import Disposition, QualityOutcome, RejectRecord, Severity

__all__ = [
    "quality_gate",
    "Disposition",
    "Severity",
    "QualityOutcome",
    "RejectRecord",
]
