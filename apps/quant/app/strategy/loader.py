"""策略加载器 — 三层目录热加载 + META 校验 + 信号协议适配。

三层目录（权限分明，AI 永不进 builtin）：
- builtin/  ：随镜像维护（source="builtin"）
- custom/   ：用户手写（source="custom"，文件名建议 custom_ 前缀）
- ai/       ：AI 生成（source="ai"，文件名 ai_ 前缀，先经 ai/validator 校验才可入此目录）

加载容错（与 tick-stock-panel 一致）：单文件坏不波及其他，记入 load_errors。
"""
from __future__ import annotations

import importlib.util
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import numpy as np

from app.matrix import EnrichedMatrix
from app.strategy.base import StrategySignals, empty_signals
from app.strategy.composite import (
    MAX_COMPOSITE_CHILDREN,
    merge_signal_matrices,
)

logger = logging.getLogger(__name__)

# META 必填键与类型（宽松校验：缺键报错，多余键放行——向前兼容）
_META_REQUIRED = {"id": str, "name": str}
# 内置评分字段（与 enriched 指标 + OHLCV 字段对齐，防 AI 编造评分列）。
# 本 frozenset 保持纯内置、全局不变；用户 active 因子经 allowed_scoring_fields()
# 动态并入（user_id 为空时白名单 == 本集合，与阶段 K6 前行为完全一致）。
ALLOWED_SCORING_FIELDS = frozenset({
    "open", "high", "low", "close", "volume", "amount",
    "ma5", "ma10", "ma20", "ma60", "ema12", "ema26",
    "macd_dif", "macd_dea", "macd_hist", "rsi14",
    "boll_upper", "boll_lower", "momentum_5d", "momentum_20d",
    "vol_ratio_5d", "high_20d", "low_20d",
})


def allowed_scoring_fields(user_id: str | None = None) -> frozenset[str]:
    """动态合成评分白名单：内置字段 ∪ 当前用户 active 状态的用户因子 id（uf_*/cf_*）。

    多用户隔离（G4）：只查「builtin 全局 + 本人私有」命名空间，他人的 uf_* id
    不在本人白名单内（校验即拒）。user_id 为空 / 查询异常时返回纯内置集合
    （优雅降级，注册表不可达绝不崩策略加载）。
    """
    if not user_id:
        return ALLOWED_SCORING_FIELDS
    try:
        from app.mining.factors import active_user_factors
        user_ids = {spec.id for spec in active_user_factors(user_id)}
    except Exception as e:  # 注册表/磁盘不可达：降级纯内置（绝不崩加载）
        logger.warning("用户 %s 因子白名单合成失败，降级纯内置：%s", user_id, e)
        return ALLOWED_SCORING_FIELDS
    return ALLOWED_SCORING_FIELDS | frozenset(user_ids)


def user_factor_values(
    scoring: dict, enriched: EnrichedMatrix, user_id: str | None
) -> dict[str, np.ndarray]:
    """把 scoring 中引用的用户因子列求值注入，返回 {因子id: (dates × symbols)}。

    内置字段不在此处理（调用方直接 enriched["col"] 取）；用户因子（uf_*）经
    DSL 编译产物 evaluate() 求值，cf_* 经挖掘目录同款加权 zscore 合成。
    求值失败/全 NaN 的因子缺席返回 dict（优雅降级，调用方按缺失字段跳过）。
    """
    if not user_id:
        return {}
    builtin = ALLOWED_SCORING_FIELDS
    extra = [k for k in scoring if k not in builtin]
    if not extra:
        return {}
    from app.factors import registry as _reg
    from app.mining.factors import _evaluate_user_factor
    out: dict[str, np.ndarray] = {}
    for fid in extra:
        spec = _reg.get_factor(fid, user_id)  # builtin + 本人私有（不越界）
        if spec is None or spec.kind not in ("custom", "composite"):
            continue
        try:
            vals = _evaluate_user_factor(spec, enriched, user_id)
        except Exception as e:  # 防御性兜底：单因子失败不波及其他评分列
            logger.warning("评分因子 %s 求值异常，跳过：%s", fid, e)
            continue
        if vals is not None:
            out[fid] = vals
    return out


@dataclass
class StrategyDef:
    """加载后的策略定义（只读元数据 + 计算函数引用）。"""
    meta: dict
    compute_fn: Callable[[EnrichedMatrix, dict], StrategySignals]
    source: str
    file_path: Path
    params_schema: list[dict] = field(default_factory=list)
    # 归一化后的时间维度：["1d"]（默认）/ ["1m"] / ["1d","1m"]；
    # 含 "1m" 的策略走分钟回放路径（engine/minute_replay），纯 "1d" 走矩阵回测。
    timeframes: list[str] = field(default_factory=lambda: ["1d"])
    # 分钟回放的日线窗口长度（T-1 往前的完成态日K 根数）；0/None = 不用日线窗口
    minute_daily_bars: int = 0
    # composite 叠加策略声明（kind="composite" 时非空）：
    # [(child_strategy_id, weight), ...]，顺序与 META["children"] 对齐。
    composite_children: list[tuple[str, float]] = field(default_factory=list)
    composite_merge_mode: str = "union"   # union | intersect
    composite_min_confirm: int = 0        # intersect 模式下命中的最少子策略数；0=全部

    @property
    def strategy_id(self) -> str:
        return str(self.meta["id"])

    @property
    def name(self) -> str:
        return str(self.meta.get("name", self.strategy_id))

    @property
    def stop_loss(self) -> float | None:
        v = self.meta.get("stop_loss")
        return float(v) if v is not None else None

    @property
    def max_hold_days(self) -> int | None:
        v = self.meta.get("max_hold_days")
        return int(v) if v is not None else None

    @property
    def is_minute_strategy(self) -> bool:
        """是否分钟频策略（timeframes 含 "1m"）：走分钟回放而非矩阵回测。"""
        return "1m" in self.timeframes

    @property
    def is_composite(self) -> bool:
        """是否叠加策略（META kind="composite"）：由多个子策略信号合并而成。"""
        return str(self.meta.get("kind", "")).lower() == "composite"


def _parse_composite_children(raw: Any, sid: str) -> list[tuple[str, float]]:
    """解析 META["children"] 为 [(child_id, weight), ...]。

    每项形如 {"strategy_id": "xxx", "weight": 0.4}（weight 缺省 1.0）。
    结构问题直接拒绝（raise）——composite 声明错误不该静默降级成怪策略：
    - 非空 list，每项含非空 strategy_id 与非负数值 weight
    - 子策略 id 不重复、不含自引用
    - 数量 <= MAX_COMPOSITE_CHILDREN（防信号计算成本/OOM 爆炸，对齐参照实现）
    """
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"composite 策略 {sid} 的 META['children'] 必须是非空 list")
    if len(raw) > MAX_COMPOSITE_CHILDREN:
        raise ValueError(
            f"composite 策略 {sid} 子策略数 {len(raw)} 超过上限 {MAX_COMPOSITE_CHILDREN}"
        )
    children: list[tuple[str, float]] = []
    seen: set[str] = set()
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"composite 策略 {sid} 的 children[{i}] 必须是 dict")
        cid = item.get("strategy_id")
        if not isinstance(cid, str) or not cid:
            raise ValueError(f"composite 策略 {sid} 的 children[{i}] 缺少非空 'strategy_id'")
        if cid == sid:
            raise ValueError(f"composite 策略 {sid} 的 children[{i}] 不允许自引用")
        if cid in seen:
            raise ValueError(f"composite 策略 {sid} 的 children[{i}] 子策略 {cid!r} 重复")
        seen.add(cid)
        try:
            weight = float(item.get("weight", 1.0))
        except (TypeError, ValueError) as e:
            raise ValueError(f"composite 策略 {sid} 的 children[{i}] weight 必须是数值") from e
        if weight < 0:
            raise ValueError(f"composite 策略 {sid} 的 children[{i}] weight 必须 >= 0")
        children.append((cid, weight))
    return children


def _parse_composite_merge(meta: dict, sid: str) -> tuple[str, int]:
    """解析 merge_mode / min_confirm（非法值告警降级，不崩加载）。"""
    merge_mode = str(meta.get("merge_mode", "union")).lower()
    if merge_mode not in ("union", "intersect"):
        logger.warning(
            "composite 策略 %s 的 merge_mode %r 非法，已降级 union", sid, merge_mode,
        )
        merge_mode = "union"
    try:
        min_confirm = int(meta.get("min_confirm") or 0)
    except (TypeError, ValueError):
        logger.warning("composite 策略 %s 的 min_confirm 非整数，已按 0 处理", sid)
        min_confirm = 0
    return merge_mode, max(min_confirm, 0)


def _normalize_timeframes(raw: Any, sid: str) -> list[str]:
    """把 META["timeframes"] 归一化为 ["1d"]/["1m"]/["1d","1m"]（缺省 ["1d"]）。

    容错（与 _normalize_params 同风格）：只认 "1d"/"1m"，其余值告警丢弃；
    全部非法时降级 ["1d"]（纯日频），绝不让 META 写法问题崩加载。
    """
    if raw is None:
        return ["1d"]
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, (list, tuple)):
        logger.warning("策略 %s 的 timeframes 非标准格式（%s），已降级 [\"1d\"]", sid, type(raw).__name__)
        return ["1d"]
    valid = [t for t in raw if t in ("1d", "1m")]
    bad = [t for t in raw if t not in ("1d", "1m")]
    if bad:
        logger.warning("策略 %s 的 timeframes 含未知值 %s，已忽略", sid, bad)
    if not valid:
        return ["1d"]
    # 去重保序
    out: list[str] = []
    for t in valid:
        if t not in out:
            out.append(t)
    return out


def _normalize_params(raw: Any, sid: str) -> list[dict]:
    """把 META["params"] 归一化为 list[dict]（每项含 id/label/type/default）。

    容错（对齐参照 _normalize_param_defs）：dict/list[str]/list[dict] 混写都接受，
    不可识别项丢弃并告警，整体坏则空 list 降级——绝不让 params 格式问题崩加载。
    """
    if raw is None:
        return []
    if isinstance(raw, dict):
        items = list(raw.items())
    elif isinstance(raw, list):
        items = [(p.get("id"), p) if isinstance(p, dict) else (p, None) for p in raw]
    else:
        logger.warning("策略 %s 的 params 非标准格式（%s），已降级为空", sid, type(raw).__name__)
        return []
    out: list[dict] = []
    for key, val in items:
        if not isinstance(key, str) or not key:
            continue
        item = {"id": key, **val} if isinstance(val, dict) else {"id": key, "default": val}
        item.setdefault("label", key)
        item.setdefault("type", "float")
        item.setdefault("default", None)
        out.append(item)
    return out


def _validate_meta(meta: Any, path: Path, user_id: str | None = None) -> dict:
    """校验 META 为字面量 dict 且含必填键；返回规范化后的 meta。

    scoring 白名单 = 内置字段 ∪ 当前用户 active 因子 id（动态合成）；
    user_id 为空时白名单即纯内置集合（与阶段 K6 前行为一致）。
    """
    if not isinstance(meta, dict):
        raise ValueError(f"{path.name}: META 必须是顶层字面量 dict")
    for key, typ in _META_REQUIRED.items():
        if key not in meta or not isinstance(meta[key], typ) or not meta[key]:
            raise ValueError(f"{path.name}: META 缺少必填键 {key!r}（{typ.__name__}）")
    scoring = meta.get("scoring", {})
    if isinstance(scoring, dict):
        bad = set(scoring) - allowed_scoring_fields(user_id)
        if bad:
            raise ValueError(f"{path.name}: scoring 含白名单外字段 {sorted(bad)}")
    return dict(meta)


def _load_module(path: Path):
    """importlib 加载单文件模块（AI 目录文件应先经 validator 校验，此处做执行）。"""
    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        raise ValueError(f"无法从 {path} 加载模块")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _wrap_compute(mod: Any, path: Path) -> Callable[[EnrichedMatrix, dict], StrategySignals]:
    """提取并校验策略入口 compute(enriched, params)。"""
    fn = getattr(mod, "compute", None)
    if not callable(fn):
        raise ValueError(f"{path.name}: 缺少策略入口 compute(enriched, params)")
    return fn


class StrategyRegistry:
    """策略注册表：扫描三层目录，加载/缓存全部策略定义。"""

    def __init__(self, dirs: dict[str, Path], user_id: str | None = None):
        """dirs: {"builtin": Path, "custom": Path, "ai": Path}（缺省目录跳过）。

        user_id：scoring 白名单合成的用户命名空间（该用户 active 因子 id 可用作
        scoring 字段）；为空时白名单为纯内置字段（与阶段 K6 前行为完全一致）。
        """
        self._dirs = dirs
        self._user_id = user_id
        self._strategies: dict[str, StrategyDef] = {}
        self._errors: list[dict] = []
        self.reload()

    def reload(self) -> None:
        strategies: dict[str, StrategyDef] = {}
        errors: list[dict] = []
        for source in ("builtin", "custom", "ai"):
            d = self._dirs.get(source)
            if d is None or not d.exists():
                continue
            for f in sorted(d.glob("*.py")):
                if f.name.startswith("_"):
                    continue
                try:
                    s = self._load_file(f, source, self._user_id)
                    sid = s.strategy_id
                    if sid in strategies:
                        raise ValueError(f"策略 id 重复 {sid!r}（{f.name}）")
                    strategies[sid] = s
                except Exception as e:  # 单文件坏不波及其他（插件隔离）
                    logger.warning("加载策略失败 %s：%s", f.name, e)
                    errors.append({"file": str(f), "source": source, "error": str(e)})
        # 第二阶段：校验 composite 引用合法性（子策略须已注册/存在且为日频叶子，
        # 禁止嵌套/分钟频）。孤儿 composite 降级移除并记入 errors，
        # 绝不把半截引用留给执行期。
        for sid in [s for s, d in strategies.items() if d.is_composite]:
            sdef = strategies[sid]
            err = None
            for cid, _w in sdef.composite_children:
                child = strategies.get(cid)
                if child is None:
                    err = f"composite 策略 {sid} 引用的子策略 {cid!r} 不存在"
                    break
                if child.is_composite:
                    err = f"composite 策略 {sid} 引用的子策略 {cid!r} 也是 composite（禁止嵌套）"
                    break
                if child.is_minute_strategy:
                    err = f"composite 策略 {sid} 暂不支持分钟频子策略 {cid!r}"
                    break
            if err:
                logger.warning("%s，已从注册表移除", err)
                errors.append({"file": str(sdef.file_path), "source": sdef.source, "error": err})
                del strategies[sid]
        self._strategies = strategies
        self._errors = errors

    @staticmethod
    def _load_file(path: Path, source: str, user_id: str | None = None) -> StrategyDef:
        mod = _load_module(path)
        meta = _validate_meta(getattr(mod, "META", None), path, user_id)
        sid = str(meta["id"])
        composite_children: list[tuple[str, float]] = []
        composite_merge_mode = "union"
        composite_min_confirm = 0
        if str(meta.get("kind", "")).lower() == "composite":
            # 叠加策略是声明式的：不含业务代码，仅经 META["children"] 引用其他策略。
            # compute_fn 在此无法闭包捕获 registry（单文件加载阶段注册表未就绪），
            # 由 StrategyRegistry.run 在引用校验后走合并分支（见 run）。
            if getattr(mod, "compute", None) is not None:
                logger.warning(
                    "composite 策略 %s 声明了 compute 函数，已忽略（叠加策略只读 children）", sid,
                )
            composite_children = _parse_composite_children(meta.get("children"), sid)
            composite_merge_mode, composite_min_confirm = _parse_composite_merge(meta, sid)
            compute_fn = _composite_placeholder
        else:
            compute_fn = _wrap_compute(mod, path)
        # 分钟回放日线窗口长度：非正数一律按 0（不用日线窗口）容错
        try:
            daily_bars = int(meta.get("minute_daily_bars") or 0)
        except (TypeError, ValueError):
            logger.warning("策略 %s 的 minute_daily_bars 非整数，已按 0 处理", sid)
            daily_bars = 0
        return StrategyDef(
            meta=meta,
            compute_fn=compute_fn,
            source=source,
            file_path=path,
            params_schema=_normalize_params(meta.get("params"), sid),
            timeframes=_normalize_timeframes(meta.get("timeframes"), sid),
            minute_daily_bars=max(daily_bars, 0),
            composite_children=composite_children,
            composite_merge_mode=composite_merge_mode,
            composite_min_confirm=composite_min_confirm,
        )

    def get(self, strategy_id: str) -> StrategyDef:
        if strategy_id not in self._strategies:
            raise KeyError(f"策略不存在 {strategy_id!r}（已加载 {len(self._strategies)} 个）")
        return self._strategies[strategy_id]

    def all(self) -> list[StrategyDef]:
        return list(self._strategies.values())

    def load_errors(self) -> list[dict]:
        return list(self._errors)

    def run(self, strategy_id: str, enriched: EnrichedMatrix, params: dict | None = None) -> StrategySignals:
        """执行策略：入口异常时降级为空信号（不崩调用方），并记日志。"""
        s = self.get(strategy_id)
        if s.is_composite:
            return self._run_composite(s, enriched)
        merged = {**{p["id"]: p.get("default") for p in s.params_schema}, **(params or {})}
        # 阶段 K6：scoring 引用的用户因子（uf_*/cf_*）对当前矩阵只读求值，
        # 经 params["__user_factor_values__"] 注入给策略 compute() 消费；
        # 求值失败/全 NaN 的因子缺席（策略按缺失字段跳过），绝不影响回测主流程。
        scoring = s.meta.get("scoring") or {}
        if self._user_id and any(k not in ALLOWED_SCORING_FIELDS for k in scoring):
            merged["__user_factor_values__"] = user_factor_values(scoring, enriched, self._user_id)
        try:
            sig = s.compute_fn(enriched, merged)
        except Exception as e:
            logger.exception("策略 %s 执行异常，降级为空信号：%s", strategy_id, e)
            return empty_signals(enriched.base.shape)
        shape = enriched.base.shape
        if sig.entry.shape != shape or sig.exit.shape != shape:
            raise ValueError(f"策略 {strategy_id} 信号形状 {sig.entry.shape} 与矩阵 {shape} 不一致")
        return sig

    def _run_composite(self, s: StrategyDef, enriched: EnrichedMatrix) -> StrategySignals:
        """执行 composite：逐子策略 run（复用单策略口径与降级语义）→ 合并信号矩阵。

        优雅降级：子策略缺失/异常/形状不符者剔除（run 自身已把异常降级为空信号，
        此处再兜缺失与形状），全部不可用时返回空信号，绝不崩调用方。
        """
        shape = enriched.base.shape
        sigs: list[StrategySignals] = []
        weights: list[float] = []
        for cid, w in s.composite_children:
            try:
                sig = self.run(cid, enriched, None)
            except KeyError as e:  # 加载后子策略被移除等竞态：剔除不崩
                logger.warning("composite %s 的子策略不可用，剔除：%s", s.strategy_id, e)
                continue
            if sig.entry.shape != shape or sig.exit.shape != shape:
                logger.warning(
                    "composite %s 的子策略 %s 信号形状 %s 与矩阵 %s 不一致，剔除",
                    s.strategy_id, cid, sig.entry.shape, shape,
                )
                continue
            sigs.append(sig)
            weights.append(w)
        # 退出投影窗口封顶：composite META.max_hold_days 优先，缺省取各子上限的最大值
        # （窗口须盖住最长寿的子持仓，否则长尾 exit 会被错误放行到窗口外）。
        max_hold = s.max_hold_days or 0
        if max_hold <= 0:
            child_holds = [
                self._strategies[cid].max_hold_days or 0
                for cid, _ in s.composite_children
                if cid in self._strategies
            ]
            max_hold = max(child_holds, default=0)
        return merge_signal_matrices(
            sigs, weights, s.composite_merge_mode, s.composite_min_confirm,
            max_hold, shape,
        )


def _composite_placeholder(enriched: EnrichedMatrix, params: dict) -> StrategySignals:
    """composite 的占位 compute：正常路径不会执行（Registry.run 走合并分支）。

    防御性降级：万一被直接调用（绕开 Registry.run），返回空信号而非抛错。
    """
    logger.warning("composite 占位 compute 被直接调用，返回空信号")
    return empty_signals(enriched.base.shape)
