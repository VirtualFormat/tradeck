"""因子门面 — 组装 registry + dsl + store 为 HTTP 层消费的五函数契约（阶段 J4）。

契约（apps/quant/app/api.py 的 /api/factors* 端点依赖）：
- list_factors(user_id) -> list[dict]
- create_factor(user_id, spec) -> dict
- compile_preview(user_id, formula, kind, members=None) -> dict
- update_factor(user_id, factor_id, patch) -> dict
- delete_factor(user_id, factor_id) -> dict
全部按 user_id 命名空间隔离（G4 多用户骨架）。

direction 映射：HTTP 层用 1/-1（高好/低好），registry 用 high/low/none——
门面做双向转换，两端口径解耦。
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

import numpy as np

from app.factors import registry, store
from app.factors.dsl import compile_formula

logger = logging.getLogger(__name__)

# direction 双向映射：HTTP 1/-1/0 ↔ registry high/low/none
_DIR_TO_REG = {1: "high", -1: "low", 0: "none"}
_DIR_FROM_REG = {"high": 1, "low": -1, "none": 0}


def _spec_to_dict(spec, status: str | None = None) -> dict:
    """FactorSpec → HTTP 响应 dict（direction 转 1/-1/0）。"""
    return {
        "id": spec.id,
        "label": spec.label,
        "group": spec.group,
        "formula": spec.formula_text,
        "kind": spec.kind,
        "version": spec.version,
        "direction": _DIR_FROM_REG.get(spec.direction, 0),
        "status": status,
        "warmup_bars": spec.warmup_bars,
        "members": (
            [{"id": fid, "weight": w} for fid, w in spec.components]
            if spec.components else None
        ),
    }


def list_factors(user_id: str) -> list[dict]:
    """列出当前用户可见的全部因子（builtin + 用户 uf_*/cf_*）。

    用户因子状态从 store 读（注册表 spec 不含 status）；启动时先把该用户
    磁盘上的因子重放进其私有命名空间（幂等）；builtin base 全局共享。
    """
    store.load_into_registry(user_id)
    status_of: dict[str, str] = {}
    for d in store.load_all(user_id):
        if d.get("id"):
            status_of[d["id"]] = d.get("status", store.STATUS_DRAFT)
    return [
        _spec_to_dict(spec, status_of.get(spec.id))
        for spec in registry.list_factors(user_id=user_id)
    ]


def _definition_of(user_id: str, spec: dict) -> dict:
    """HTTP spec（direction 1/-1）→ store 定义（direction high/low/none）。"""
    return {
        "id": spec["id"],
        "label": spec["label"],
        "group": spec.get("group", "自定义"),
        "kind": "composite" if spec.get("kind") == "cf" else "custom",
        "formula": spec.get("formula", ""),
        "components": (
            [(m["id"], float(m.get("weight", 1.0))) for m in spec["members"]]
            if spec.get("members") else None
        ),
        "direction": _DIR_TO_REG.get(int(spec.get("direction", 1)), "high"),
        "status": spec.get("status", store.STATUS_DRAFT),
    }


def create_factor(user_id: str, spec: dict) -> dict:
    """创建自定义因子：校验 → 落盘 → 注册。返回注册后的 spec dict。"""
    created = store.create_factor(user_id, _definition_of(user_id, spec))
    return _spec_to_dict(created, spec.get("status", store.STATUS_DRAFT))


def update_factor(user_id: str, factor_id: str, patch: dict) -> dict:
    """更新因子：公式/成员变更 version+1；状态流转走状态机校验。"""
    defs = {d["id"]: d for d in store.load_all(user_id)}
    current = defs.get(factor_id)
    if current is None:
        raise ValueError(f"因子不存在: {factor_id}")

    # 状态流转（独立字段，走状态机合法边校验）
    new_status = patch.get("status")
    if new_status is not None:
        store.transition(user_id, factor_id, new_status)
        current["status"] = new_status

    # 公式/成员/元数据变更
    changed = False
    for key in ("label", "group", "formula"):
        if patch.get(key) is not None:
            current[key] = patch[key]
            changed = True
    if patch.get("members") is not None:
        current["components"] = [
            (m["id"], float(m.get("weight", 1.0))) for m in patch["members"]
        ]
        changed = True
    if patch.get("direction") is not None:
        current["direction"] = _DIR_TO_REG.get(int(patch["direction"]), "high")
        changed = True

    if changed:
        # 公式/成员变更 → version+1（create_factor 检测变更自动升级版本）
        spec = store.create_factor(user_id, current)
        return _spec_to_dict(spec, current.get("status"))
    # 仅状态变更
    spec = registry.get_factor(factor_id, user_id)
    if spec is None:
        store.load_into_registry(user_id)
        spec = registry.get_factor(factor_id, user_id)
    return _spec_to_dict(spec, current.get("status"))


def delete_factor(user_id: str, factor_id: str) -> dict:
    """删除用户因子（builtin 由 HTTP 层拦截，这里双保险）。"""
    if not (factor_id.startswith("uf_") or factor_id.startswith("cf_")):
        raise ValueError(f"内置因子不可删除: {factor_id}")
    ok = store.delete_one(user_id, factor_id)
    if ok:
        registry.unregister_factor(factor_id, user_id)  # 只影响本人命名空间
    return {"id": factor_id, "deleted": ok}


def _preview_matrix():
    """编译预览的样例矩阵：读一只流动性好的缓存标的（缺失则合成）。"""
    from app.data import store as data_store
    from app.matrix import build, enrich

    for probe in ("600519.SH", "000001.SZ"):
        df = data_store.load(probe)
        if not df.is_empty() and df.height >= 60:
            end = df["date"][-1]
            start = end - timedelta(days=120)
            m = build([probe], start, end)
            if m.dates:
                return enrich(m)
    # 无缓存数据：合成一段随机游走（预览降级，不阻塞编译诊断）
    from app.matrix import MarketMatrix
    rng = np.random.default_rng(42)
    n = 60
    close = 10 + np.cumsum(rng.normal(0, 0.2, (n, 1)), axis=0)
    dates = [date(2026, 1, 5) + timedelta(days=i) for i in range(n)]
    m = MarketMatrix(
        dates=dates, symbols=["__preview__"],
        open=close - 0.05, high=close + 0.1, low=close - 0.1, close=close,
        volume=np.full((n, 1), 1e6), amount=close * 1e6,
    )
    return enrich(m)


def compile_preview(
    user_id: str, formula: str, kind: str, members: list | None = None
) -> dict:
    """编译诊断 + 样例数据即时预览。

    编译失败恒 ok=False + errors（诊断是成功响应，不抛错）；成功时附样例矩阵的
    因子值摘要（mean/std/min/max/valid_ratio + 尾部 sample_values 供预览折线）。
    """
    if kind == "cf":
        members = members or []
        if not members:
            return {"ok": False, "errors": [{"code": "E020", "message": "复合因子至少需 1 个成员"}]}
        missing = [
            m["id"] for m in members
            if registry.get_factor(m["id"], user_id) is None  # builtin + 本人私有
        ]
        if missing:
            return {"ok": False, "errors": [{"code": "E021", "message": f"成员因子未注册: {missing}"}]}
        return {"ok": True, "errors": [], "preview": None,
                "note": "复合因子为成员加权合成，预览需逐成员展开（矩阵层），此处仅校验成员有效性"}

    compiled = compile_formula(formula or "", user_id=user_id)
    if not compiled.ok:
        return {
            "ok": False,
            "errors": [
                {"code": e.code, "message": e.message,
                 "position": getattr(e, "position", None)}
                for e in compiled.errors
            ],
        }

    preview = None
    try:
        en = _preview_matrix()
        vals = compiled.evaluate(en)
        if vals is not None:
            flat = vals[:, 0] if vals.ndim == 2 else vals
            valid = flat[np.isfinite(flat)]
            if valid.size:
                tail = en.base.dates[-min(30, len(en.base.dates)):]
                tail_vals = vals[-len(tail):, 0] if vals.ndim == 2 else vals[-len(tail):]
                preview = {
                    "mean": float(np.mean(valid)),
                    "std": float(np.std(valid)),
                    "min": float(np.min(valid)),
                    "max": float(np.max(valid)),
                    "valid_ratio": float(valid.size / flat.size),
                    "sample_values": [
                        {"date": d.isoformat(),
                         "value": (None if not np.isfinite(v) else round(float(v), 6))}
                        for d, v in zip(tail, tail_vals)
                    ],
                }
    except Exception as e:  # 预览失败不阻塞编译诊断（编译已通过）
        logger.warning("因子预览求值失败（编译已通过）：%s", e)

    return {"ok": True, "errors": [], "preview": preview,
            "warmup_bars": compiled.warmup_bars,
            "cross_sectional": compiled.cross_sectional}
