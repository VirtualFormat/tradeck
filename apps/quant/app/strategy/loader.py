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

logger = logging.getLogger(__name__)

# META 必填键与类型（宽松校验：缺键报错，多余键放行——向前兼容）
_META_REQUIRED = {"id": str, "name": str}
# 允许的评分字段（与 enriched 指标 + OHLCV 字段对齐，防 AI 编造评分列）
ALLOWED_SCORING_FIELDS = frozenset({
    "open", "high", "low", "close", "volume", "amount",
    "ma5", "ma10", "ma20", "ma60", "ema12", "ema26",
    "macd_dif", "macd_dea", "macd_hist", "rsi14",
    "boll_upper", "boll_lower", "momentum_5d", "momentum_20d",
    "vol_ratio_5d", "high_20d", "low_20d",
})


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


def _validate_meta(meta: Any, path: Path) -> dict:
    """校验 META 为字面量 dict 且含必填键；返回规范化后的 meta。"""
    if not isinstance(meta, dict):
        raise ValueError(f"{path.name}: META 必须是顶层字面量 dict")
    for key, typ in _META_REQUIRED.items():
        if key not in meta or not isinstance(meta[key], typ) or not meta[key]:
            raise ValueError(f"{path.name}: META 缺少必填键 {key!r}（{typ.__name__}）")
    scoring = meta.get("scoring", {})
    if isinstance(scoring, dict):
        bad = set(scoring) - ALLOWED_SCORING_FIELDS
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

    def __init__(self, dirs: dict[str, Path]):
        """dirs: {"builtin": Path, "custom": Path, "ai": Path}（缺省目录跳过）。"""
        self._dirs = dirs
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
                    s = self._load_file(f, source)
                    sid = s.strategy_id
                    if sid in strategies:
                        raise ValueError(f"策略 id 重复 {sid!r}（{f.name}）")
                    strategies[sid] = s
                except Exception as e:  # 单文件坏不波及其他（插件隔离）
                    logger.warning("加载策略失败 %s：%s", f.name, e)
                    errors.append({"file": str(f), "source": source, "error": str(e)})
        self._strategies = strategies
        self._errors = errors

    @staticmethod
    def _load_file(path: Path, source: str) -> StrategyDef:
        mod = _load_module(path)
        meta = _validate_meta(getattr(mod, "META", None), path)
        compute_fn = _wrap_compute(mod, path)
        sid = str(meta["id"])
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
        merged = {**{p["id"]: p.get("default") for p in s.params_schema}, **(params or {})}
        try:
            sig = s.compute_fn(enriched, merged)
        except Exception as e:
            logger.exception("策略 %s 执行异常，降级为空信号：%s", strategy_id, e)
            return empty_signals(enriched.base.shape)
        shape = enriched.base.shape
        if sig.entry.shape != shape or sig.exit.shape != shape:
            raise ValueError(f"策略 {strategy_id} 信号形状 {sig.entry.shape} 与矩阵 {shape} 不一致")
        return sig
