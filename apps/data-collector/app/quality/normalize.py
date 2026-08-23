"""标准化（REPAIR）：写库前的类型/单位/symbol 归一。

只修「确定可修」的：字符串数值转 float、symbol 去空白转大写。
不做任何猜测性补全（缺值不补、异常不改写为「合理值」）。
"""
from __future__ import annotations

from typing import Any

from app.quality.rules import QualityRule

# 各表应转数值的字段（宽松转换，失败保留原值交校验拦截）。
# volume 单独按 int 归一：这些列是 BIGINT，归一成 float 会让 asyncpg 报类型错。
_INT_FIELDS: dict[str, tuple[str, ...]] = {
    "daily_prices": ("volume",),
    "quote_snapshots": ("volume",),
    "index_prices": ("volume",),
    "minute_bars": ("volume", "ts"),  # ts 为 UTC epoch 秒（整型）
}
_NUMERIC_FIELDS: dict[str, tuple[str, ...]] = {
    "daily_prices": ("open", "high", "low", "close", "amount"),
    "quote_snapshots": ("last_price", "change", "change_percent"),
    "index_prices": ("close",),
    "macro_asset_prices": ("close",),
    "minute_bars": ("open", "high", "low", "close", "amount"),
}


def _to_number(v: Any) -> Any:
    """字符串数值转 float；无法转或非字符串原样返回。"""
    if not isinstance(v, str):
        return v
    s = v.strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return v  # 交给校验器拦


def _to_int(v: Any) -> Any:
    """字符串整数转 int；无法转或非字符串原样返回（交校验拦截）。"""
    if not isinstance(v, str):
        return v
    s = v.strip()
    if not s:
        return None
    try:
        return int(float(s))  # 容忍 "123.0" 形式
    except ValueError:
        return v


def normalize_row(rule: QualityRule, row: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """归一单行。返回 (归一后的行, 是否发生了修复)。"""
    repaired = False
    out = dict(row)

    # symbol 归一：去空白 + 大写
    sf = rule.symbol_field
    sym = out.get(sf)
    if isinstance(sym, str):
        cleaned = sym.strip().upper()
        if cleaned != sym:
            out[sf] = cleaned
            repaired = True

    # 数值字段：字符串 → float
    for f in _NUMERIC_FIELDS.get(rule.table, ()):
        v = out.get(f)
        if isinstance(v, str):
            nv = _to_number(v)
            if nv is not v:
                out[f] = nv
                repaired = True

    # 整数字段（BIGINT 列）：字符串 → int，避免 float 触发 asyncpg 类型错
    for f in _INT_FIELDS.get(rule.table, ()):
        v = out.get(f)
        if isinstance(v, str):
            nv = _to_int(v)
            if nv is not v:
                out[f] = nv
                repaired = True

    return out, repaired
