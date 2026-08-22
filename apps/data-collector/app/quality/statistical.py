"""P2 统计标记：可疑但放行（只标记不拦截，供量化侧自决可信度）。

与 P0/P1 的单行物理校验不同，P2 是批级统计检测——需要跨行比较：
批内 Z-score 离群、日K 跳空。被标记的行仍 ACCEPT 入库，但落 quarantine
表（severity=P2）供审计与量化侧参考——质量层永不因统计可疑而饿死管道。
"""
from __future__ import annotations

import logging
import statistics
from typing import Any

from app.quality.models import RejectRecord, Severity

logger = logging.getLogger(__name__)

# Z-score 离群阈值（|z| > 8 极宽松：只标「几乎不可能」的离群，不误标真实异动）
_ZSCORE_THRESHOLD = 8.0
# 日K 跳空阈值（|open/prev_close - 1| > 50% 才标记，跨市场最宽）
_GAP_THRESHOLD = 0.5


def _fnum(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else f


def detect_outliers_zscore(
    table: str,
    rows: list[dict[str, Any]],
    field: str,
    symbol_field: str = "symbol",
) -> list[RejectRecord]:
    """批内某字段 Z-score 离群（P2 标记，不拦）。样本 <10 不检测（无统计意义）。"""
    values = [(r, _fnum(r.get(field))) for r in rows]
    values = [(r, v) for r, v in values if v is not None]
    if len(values) < 10:
        return []

    nums = [v for _, v in values]
    try:
        mean = statistics.fmean(nums)
        stdev = statistics.stdev(nums)
    except statistics.StatisticsError:
        return []
    if stdev == 0:
        return []

    marks = []
    for row, v in values:
        z = (v - mean) / stdev
        if abs(z) > _ZSCORE_THRESHOLD:
            marks.append(
                RejectRecord(
                    source_table=table,
                    symbol=row.get(symbol_field),
                    raw_payload=row,
                    reject_reason=f"P2 统计离群: {field}={v}（z={z:.1f}，批均值={mean:.4g}）",
                    severity=Severity.P2,
                )
            )
    return marks


def detect_daily_gaps(
    table: str,
    rows: list[dict[str, Any]],
    symbol_field: str = "symbol",
) -> list[RejectRecord]:
    """日K 跳空检测（P2 标记，不拦）：按 symbol 分组排序，比较相邻 open/前收。"""
    by_symbol: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        sym = r.get(symbol_field)
        if sym:
            by_symbol.setdefault(sym, []).append(r)

    marks = []
    for sym, srows in by_symbol.items():
        ordered = sorted(srows, key=lambda r: str(r.get("date", "")))
        prev_close: float | None = None
        for row in ordered:
            o = _fnum(row.get("open"))
            if prev_close and o is not None and prev_close > 0:
                gap = abs(o / prev_close - 1)
                if gap > _GAP_THRESHOLD:
                    marks.append(
                        RejectRecord(
                            source_table=table,
                            symbol=sym,
                            raw_payload=row,
                            reject_reason=f"P2 跳空: open={o} 前收={prev_close}（跳空 {gap:.1%}）",
                            severity=Severity.P2,
                        )
                    )
            c = _fnum(row.get("close"))
            if c is not None:
                prev_close = c
    return marks
