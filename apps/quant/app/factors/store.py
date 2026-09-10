"""自定义/复合因子存储（J3）— {QUANT_CACHE_DIR}/users/{uid}/factors/{factor_id}.json。

多用户命名空间与策略目录同构（runner._user_root 布局）；单文件损坏只禁用
该因子并告警，不影响启动（对齐 tick-stock-panel factors/store.py）。

三类因子：
- uf_*：用户 DSL 因子，公式经 dsl.compile_formula 编译验证后才允许注册；
- cf_*：复合因子，<=8 个成员加权，成员引用 uf/base/virtual；
- base/virtual：系统内置，不落盘。

生命周期状态机：draft -> active -> watch -> retired（字段现在就建，
流转由 transition() 校验合法边，巡检联动逻辑随挖掘阶段启用）。
公式变更 version+1（进缓存键）。
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from app.config import settings
from app.factors.dsl import BASE_COLUMNS, compile_formula
from app.factors.registry import (
    FactorSpec,
    factor_dependencies,
    get_factor,
    register_factor,
    unregister_factor,
)

logger = logging.getLogger(__name__)

CUSTOM_ID_PATTERN = re.compile(r"^uf_[a-z0-9_]{1,40}$")
COMPOSITE_ID_PATTERN = re.compile(r"^cf_[a-z0-9_]{1,40}$")
MAX_COMPOSITE_MEMBERS = 8

STATUS_DRAFT, STATUS_ACTIVE, STATUS_WATCH, STATUS_RETIRED = "draft", "active", "watch", "retired"
STATUSES = frozenset({STATUS_DRAFT, STATUS_ACTIVE, STATUS_WATCH, STATUS_RETIRED})
# 合法流转边：draft->active->watch->retired 单向，retired 为终态（复活=新建版本）
_TRANSITIONS = {
    STATUS_DRAFT: {STATUS_ACTIVE},
    STATUS_ACTIVE: {STATUS_WATCH, STATUS_RETIRED},
    STATUS_WATCH: {STATUS_ACTIVE, STATUS_RETIRED},
    STATUS_RETIRED: set(),
}


def _dir(user_id: str, cache_dir: str | None = None) -> Path:
    directory = Path(cache_dir or settings.QUANT_CACHE_DIR) / "users" / user_id / "factors"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _path(user_id: str, factor_id: str, cache_dir: str | None = None) -> Path:
    return _dir(user_id, cache_dir) / f"{factor_id}.json"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def load_all(user_id: str, cache_dir: str | None = None) -> list[dict]:
    """读取该用户全部自定义/复合因子定义；损坏文件跳过并告警，不影响启动。"""
    out: list[dict] = []
    for file in sorted(_dir(user_id, cache_dir).glob("*.json")):
        try:
            out.append(json.loads(file.read_text(encoding="utf-8")))
        except Exception as exc:
            logger.warning("custom factor 文件损坏，跳过 %s: %s", file.name, exc)
    return out


def save_one(user_id: str, definition: dict, cache_dir: str | None = None) -> None:
    target = _path(user_id, str(definition["id"]), cache_dir)
    target.write_text(json.dumps(definition, ensure_ascii=False, indent=2), encoding="utf-8")


def delete_one(user_id: str, factor_id: str, cache_dir: str | None = None) -> bool:
    """删除因子文件并从注册表注销（未注册/文件不存在均为幂等 False）。"""
    target = _path(user_id, factor_id, cache_dir)
    existed = target.exists()
    if existed:
        target.unlink()
    try:
        unregister_factor(factor_id, user_id)  # 只注销本人命名空间，不影响其他用户
    except ValueError:
        pass  # 内置 id 不可能落在此目录，防御性吞掉
    return existed


def transition(user_id: str, factor_id: str, new_status: str, cache_dir: str | None = None) -> dict:
    """状态机流转；非法边抛 ValueError（调用方 fail-closed）。"""
    target = _path(user_id, factor_id, cache_dir)
    if not target.exists():
        raise ValueError(f"因子不存在: {factor_id}")
    definition = json.loads(target.read_text(encoding="utf-8"))
    old = str(definition.get("status", STATUS_DRAFT))
    if new_status not in STATUSES:
        raise ValueError(f"status 必须是 {sorted(STATUSES)} 之一")
    if new_status == old:
        return definition
    if new_status not in _TRANSITIONS.get(old, set()):
        raise ValueError(f"非法状态流转: {old} -> {new_status}")
    definition["status"] = new_status
    definition["updated_at"] = _now()
    save_one(user_id, definition, cache_dir)
    # 状态变化不改公式，按原 version 幂等重注册刷新 spec
    try:
        register_definition(definition, user_id=user_id, bump_version=False)
    except ValueError as exc:
        logger.warning("状态流转后重注册失败 %s: %s", factor_id, exc)
    return definition


def to_spec(definition: dict, user_id: str | None = None) -> FactorSpec:
    """定义 -> FactorSpec；校验失败抛 ValueError（调用方 fail-closed）。

    custom：依赖/预热由 DSL 编译推导（编译失败即拒绝注册）。
    composite：依赖 = 成员递归展开；预热 = 成员最大值；循环引用拒绝。
    user_id 为因子引用解析的命名空间（builtin 全局 + 当前用户私有）。
    """
    kind = str(definition.get("kind", "custom"))
    factor_id = str(definition.get("id", ""))
    label = str(definition.get("label", "")).strip()
    if not label:
        raise ValueError("label 不能为空")
    pattern = COMPOSITE_ID_PATTERN if kind == "composite" else CUSTOM_ID_PATTERN
    if not pattern.match(factor_id):
        raise ValueError(f"id 必须匹配 {pattern.pattern}")
    status = str(definition.get("status", STATUS_DRAFT))
    if status not in STATUSES:
        raise ValueError(f"status 必须是 {sorted(STATUSES)} 之一")

    if kind == "custom":
        formula = str(definition.get("formula", ""))
        compiled = compile_formula(formula, user_id=user_id)
        if not compiled.ok:
            first = compiled.errors[0]
            raise ValueError(f"公式无效 [{first.code}]: {first.message}")
        return FactorSpec(
            id=factor_id,
            label=label,
            group=str(definition.get("group", "自定义")),
            formula_text=formula,
            kind="custom",
            version=int(definition.get("version", 1)),
            dependencies=frozenset(compiled.dependencies),
            warmup_bars=compiled.warmup_bars,
            direction=str(definition.get("direction", "none")),  # type: ignore[arg-type]
        )

    if kind != "composite":
        raise ValueError(f"未知 kind: {kind}")
    members_raw = definition.get("members")
    if not isinstance(members_raw, dict) or not (2 <= len(members_raw) <= MAX_COMPOSITE_MEMBERS):
        raise ValueError(f"composite 成员必须是 2~{MAX_COMPOSITE_MEMBERS} 个")
    components: list[tuple[str, float]] = []
    for member_id, weight in members_raw.items():
        member_id = str(member_id)
        if member_id == factor_id:
            raise ValueError("composite 不能引用自身")
        try:
            weight = float(weight)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"成员 {member_id} 权重必须是数字") from exc
        if not weight:
            raise ValueError(f"成员 {member_id} 权重不能为 0")
        # 成员 = 注册表因子（builtin 全局 + 当前用户私有）或基准列（矩阵已物化，可直接参与组合）
        if get_factor(member_id, user_id) is None and member_id not in BASE_COLUMNS:
            raise ValueError(f"未知成员因子: {member_id}")
        components.append((member_id, weight))
    # 环检测沿 components 链走（依赖已展开，看不到链路成员）
    seen = {factor_id}
    frontier = [member_id for member_id, _ in components]
    while frontier:
        current = frontier.pop()
        if current in seen:
            raise ValueError("composite 成员存在循环引用")
        seen.add(current)
        current_spec = get_factor(current, user_id)
        if current_spec is not None and current_spec.kind == "composite":
            frontier.extend(member_id for member_id, _ in current_spec.components)
    dependencies = factor_dependencies([member_id for member_id, _ in components], user_id)
    warmup = max(
        ((get_factor(m, user_id).warmup_bars if get_factor(m, user_id) else 1) for m, _ in components),
        default=1,
    )
    formula_text = " + ".join(f"{weight:g}*zscore({member_id})" for member_id, weight in components)
    return FactorSpec(
        id=factor_id,
        label=label,
        group=str(definition.get("group", "组合")),
        formula_text=formula_text,
        kind="composite",
        version=int(definition.get("version", 1)),
        dependencies=dependencies,
        warmup_bars=warmup,
        direction=str(definition.get("direction", "none")),  # type: ignore[arg-type]
        components=tuple(components),
    )


def register_definition(definition: dict, user_id: str | None = None, bump_version: bool = True) -> FactorSpec:
    """定义 -> spec -> 注册。

    bump_version=True（默认）：同 id 已存在时 version+1（公式变更进缓存键）；
    bump_version=False：按定义中的 version 原样注册（启动期重放/状态流转等
    不改公式的场景），同版本冲突时返回现有 spec（幂等）。
    user_id 决定注册进哪个用户的私有命名空间。
    """
    spec = to_spec(definition, user_id=user_id)
    existing = get_factor(spec.id, user_id)
    if existing is not None and existing.version >= spec.version:
        if not bump_version:
            return existing
        spec = replace(spec, version=existing.version + 1)
        definition["version"] = spec.version
    register_factor(spec, user_id)
    return spec


def create_factor(user_id: str, definition: dict, cache_dir: str | None = None) -> FactorSpec:
    """创建因子：校验 -> 落盘 -> 注册。校验失败抛 ValueError，不落盘。"""
    definition = dict(definition)
    definition.setdefault("status", STATUS_DRAFT)
    definition["updated_at"] = _now()
    spec = to_spec(definition, user_id=user_id)  # 先验证，失败不落盘
    existing = get_factor(spec.id, user_id)  # 只查「builtin + 本人」，不越界看他人
    if existing is not None:
        # 公式/成员变更走版本升级；未变更则幂等拒绝
        changed = (
            existing.formula_text != spec.formula_text
            or existing.components != spec.components
        )
        if not changed:
            raise ValueError(f"因子已存在且定义未变更: {spec.id}")
        definition["version"] = existing.version + 1
        spec = to_spec(definition, user_id=user_id)
    save_one(user_id, definition, cache_dir)
    register_factor(spec, user_id)
    return spec


def load_into_registry(user_id: str, cache_dir: str | None = None) -> list[str]:
    """启动期把该用户存储中的因子注册进其私有命名空间；单个失败只跳过并告警。

    多轮加载：composite 成员可能引用尚未加载的 custom/其他 composite
    （文件按字母序加载，cf_* 先于 uf_*），失败的 composite 延后重试；
    重试用尽仍失败的只告警不阻塞启动。
    """
    loaded: list[str] = []
    pending = list(load_all(user_id, cache_dir))
    for round_index in range(3):
        deferred: list[dict] = []
        for definition in pending:
            try:
                register_definition(definition, user_id=user_id, bump_version=False)
                loaded.append(str(definition["id"]))
            except ValueError:
                if round_index < 2 and str(definition.get("kind")) == "composite":
                    deferred.append(definition)
                else:
                    logger.warning("custom factor 注册失败 %s", definition.get("id"), exc_info=True)
            except Exception:
                logger.warning("custom factor 注册失败 %s", definition.get("id"), exc_info=True)
        if not deferred:
            break
        pending = deferred
    return loaded
