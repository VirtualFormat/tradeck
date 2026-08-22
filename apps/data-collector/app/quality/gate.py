"""quality_gate：写库 job 的统一质量入口。

流水线：normalize（REPAIR 归一）→ validate（P0/P1 拦截）→ 落 quarantine/metrics。
返回合格行列表，job 直接拿去 UPSERT。

铁律映射：本函数任何环节异常都记日志并**放行全部原始行**（宁可漏拦，
不可误停数据管道）。未登记规则的表直接放行（向后兼容，新表逐步接入）。
"""
from __future__ import annotations

import logging
from typing import Any

from app.quality.models import QualityOutcome, RejectRecord, Severity
from app.quality.normalize import normalize_row
from app.quality.rules import get_rule, validate_row
from app.quality.statistical import detect_daily_gaps, detect_outliers_zscore
from app.quality.store import store_metrics, store_rejects

logger = logging.getLogger(__name__)


def _process(table: str, rows: list[dict[str, Any]]) -> QualityOutcome:
    """纯处理（不碰 DB）：归一 + 校验，返回质量结论。便于单测。"""
    rule = get_rule(table)
    outcome = QualityOutcome(total=len(rows))
    if rule is None:
        # 未登记规则的表：放行（向后兼容，新表逐步接入）
        outcome.accepted = list(rows)
        return outcome

    for row in rows:
        normalized, repaired = normalize_row(rule, row)
        verdict = validate_row(rule, normalized)
        if verdict is None:
            outcome.accepted.append(normalized)
            if repaired:
                outcome.repaired_count += 1
            continue

        severity, reason = verdict
        outcome.rejects.append(
            RejectRecord(
                source_table=table,
                symbol=normalized.get(rule.symbol_field),
                raw_payload=row,  # 留原始未归一的 payload 供审计
                reject_reason=reason,
                severity=severity,
            )
        )
        # P2 只标记不拦（本阶段规则暂无 P2，框架预留）
        if severity in (Severity.P0, Severity.P1):
            continue
        outcome.accepted.append(normalized)

    # P2 批级统计标记（只标记不拦）：Z-score 离群、日K 跳空
    if rule.zscore_field:
        outcome.rejects.extend(
            detect_outliers_zscore(table, outcome.accepted, rule.zscore_field, rule.symbol_field)
        )
    if rule.daily_gap:
        outcome.rejects.extend(
            detect_daily_gaps(table, outcome.accepted, rule.symbol_field)
        )

    return outcome


async def quality_gate(
    table: str,
    rows: list[dict[str, Any]],
    *,
    persist: bool = True,
) -> list[dict[str, Any]]:
    """质量闸统一入口。返回合格行（可直接 UPSERT）。

    table: 目标表名（决定用哪份规则）。
    rows: 待写行（dict 列表，键为列名）。
    persist: 是否落 quarantine/metrics（测试时可关）。
    """
    if not rows:
        return []

    try:
        outcome = _process(table, rows)
    except Exception:  # noqa: BLE001 — 质量层故障放行，不阻断管道
        logger.exception(
            "quality_gate 处理异常（table=%s，%d 行），放行全部", table, len(rows)
        )
        return list(rows)

    rejected = outcome.rejected_count
    if rejected or outcome.repaired_count:
        logger.info(
            "quality_gate %s: total=%d accepted=%d rejected=%d repaired=%d score=%s",
            table,
            outcome.total,
            outcome.total - rejected,
            rejected,
            outcome.repaired_count,
            outcome.quality_score,
        )

    if persist:
        await store_rejects(outcome.rejects)
        await store_metrics(table, outcome)

    return outcome.accepted
