"""quarantine / metrics 落库（collector 独占写，单一写者）。

data_quality_rejects：被拦数据留痕（含原始 payload、原因、严重级），可审计。
data_quality_metrics：按表按日的质量聚合（总数/合格/拦截/修复/质量分），可观测。
两表写入失败仅记日志不抛——质量层自身故障绝不阻断数据管道。
"""
from __future__ import annotations

import json
import logging
from datetime import date

from app.db import get_pool
from app.quality.models import QualityOutcome, RejectRecord

logger = logging.getLogger(__name__)


async def store_rejects(rejects: list[RejectRecord]) -> None:
    """批量落 quarantine 表。失败记日志不抛。"""
    if not rejects:
        return
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.executemany(
                """
                INSERT INTO data_quality_rejects
                    (source_table, symbol, raw_payload, reject_reason, severity)
                VALUES ($1, $2, $3::jsonb, $4, $5)
                """,
                [
                    (
                        r.source_table,
                        r.symbol,
                        json.dumps(r.raw_payload, ensure_ascii=False, default=str),
                        r.reject_reason,
                        r.severity.value,
                    )
                    for r in rejects
                ],
            )
    except Exception:  # noqa: BLE001
        logger.exception("data_quality_rejects 写入失败（%d 条），已跳过", len(rejects))


async def store_metrics(table: str, outcome: QualityOutcome) -> None:
    """按表按日 UPSERT 质量聚合。失败记日志不抛。"""
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO data_quality_metrics
                    (table_name, date, total, accepted, rejected, repaired, quality_score)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                ON CONFLICT (table_name, date) DO UPDATE SET
                    total = data_quality_metrics.total + EXCLUDED.total,
                    accepted = data_quality_metrics.accepted + EXCLUDED.accepted,
                    rejected = data_quality_metrics.rejected + EXCLUDED.rejected,
                    repaired = data_quality_metrics.repaired + EXCLUDED.repaired,
                    quality_score = EXCLUDED.quality_score,
                    updated_at = NOW()
                """,
                table,
                date.today(),
                outcome.total,
                outcome.total - outcome.rejected_count,
                outcome.rejected_count,
                outcome.repaired_count,
                outcome.quality_score,
            )
    except Exception:  # noqa: BLE001
        logger.exception("data_quality_metrics 写入失败（table=%s），已跳过", table)
