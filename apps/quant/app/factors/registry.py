"""因子注册表（J1）— 因子元数据的单一事实源。

选股评分、回测、挖掘、web 展示四端全部从注册表取因子定义，
禁止各端各自硬编码因子清单（参照 tick-stock-panel 三处清单漂移
合并为注册表的教训）。

多用户隔离（G4 铁律）：注册表分两层——
- builtin 层：_REGISTRY 只放内置 base 因子，全局只读共享，所有用户可见；
- 用户层：_USER_REGISTRIES 按 user_id 隔离存放 uf_*/cf_* 私有因子，
  用户因子只在本人命名空间可见，互不可见。
公开 API 均带可选 user_id 维度；不传 user_id 时只见 builtin（兼容旧调用）。

kind 语义：
- base：enriched 指标列 + OHLCV/amount 基准列，矩阵中已物化，无需计算；
- virtual：由 base 列表达式派生（J 阶段经 DSL 编译求值）；
- custom：用户 DSL 因子（uf_*），公式经 dsl.compile_formula 验证后注册；
- composite：复合因子（cf_*），≤8 个成员加权，成员引用 uf/base/virtual。
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Literal

Kind = Literal["base", "virtual", "composite", "custom"]
Direction = Literal["high", "low", "none"]

# enriched 指标列（apps/quant/app/matrix/enriched.py 的 enrich() 产出）
ENRICHED_INDICATORS: tuple[str, ...] = (
    "ma5",
    "ma10",
    "ma20",
    "ma60",
    "ema12",
    "ema26",
    "macd_dif",
    "macd_dea",
    "macd_hist",
    "rsi14",
    "boll_upper",
    "boll_lower",
    "momentum_5d",
    "momentum_20d",
    "vol_ratio_5d",
    "high_20d",
    "low_20d",
)

# OHLCV 基准列（MarketMatrix 字段）
OHLCV_COLUMNS: tuple[str, ...] = ("open", "high", "low", "close", "volume", "amount")

_BASE_LABELS: dict[str, tuple[str, str, str]] = {
    # id: (中文名, 分组, 描述)
    "open": ("开盘价", "行情", "当日开盘价（原始价）"),
    "high": ("最高价", "行情", "当日最高价（原始价）"),
    "low": ("最低价", "行情", "当日最低价（原始价）"),
    "close": ("收盘价", "行情", "当日收盘价（原始价）"),
    "volume": ("成交量", "行情", "当日成交量"),
    "amount": ("成交额", "行情", "当日成交额"),
    "ma5": ("MA5", "均线", "5日简单移动平均"),
    "ma10": ("MA10", "均线", "10日简单移动平均"),
    "ma20": ("MA20", "均线", "20日简单移动平均"),
    "ma60": ("MA60", "均线", "60日简单移动平均"),
    "ema12": ("EMA12", "均线", "12日指数移动平均"),
    "ema26": ("EMA26", "均线", "26日指数移动平均"),
    "macd_dif": ("MACD DIF", "趋势", "EMA12 - EMA26"),
    "macd_dea": ("MACD DEA", "趋势", "DIF 的 9 周期 EMA"),
    "macd_hist": ("MACD 柱", "趋势", "2×(DIF - DEA)，国内软件口径"),
    "rsi14": ("RSI(14)", "超买超卖", "14日相对强弱指标（Wilder 平滑）"),
    "boll_upper": ("布林上轨", "趋势", "MA20 + 2×20日标准差"),
    "boll_lower": ("布林下轨", "趋势", "MA20 - 2×20日标准差"),
    "momentum_5d": ("5日动量", "动量", "close/5日前close - 1（小数口径）"),
    "momentum_20d": ("20日动量", "动量", "close/20日前close - 1（小数口径）"),
    "vol_ratio_5d": ("5日量比", "量价", "当日成交量 / 5日均量"),
    "high_20d": ("20日最高", "价格位置", "近20日最高收盘价"),
    "low_20d": ("20日最低", "价格位置", "近20日最低收盘价"),
}


@dataclass(frozen=True)
class FactorSpec:
    """因子定义（不可变值对象）。"""

    id: str
    label: str
    group: str
    formula_text: str
    kind: Kind = "base"
    version: int = 1
    # base：空集合 = 矩阵已物化列自身；其余 kind：经 factor_dependencies 展开到 base 列
    dependencies: frozenset[str] = field(default_factory=frozenset)
    direction: Direction = "none"  # 方向以最近检验 IC 符号为准，不强填
    warmup_bars: int = 1
    # composite 专用：((成员 id, 权重), ...)；其余类型为空
    components: tuple[tuple[str, float], ...] = ()


# builtin 层：仅内置 base 因子，全局共享（只增不改，启动时一次性注册）
_REGISTRY: dict[str, FactorSpec] = {}
_CATALOG_IDS: set[str] = set()  # 内置目录（base）因子，不可注销

# 用户层：{user_id: {factor_id: FactorSpec}}，用户私有因子严格按 user_id 隔离
_USER_REGISTRIES: dict[str, dict[str, FactorSpec]] = {}

# quant 单进程 + worker 子进程内注册表读写的互斥锁
_LOCK = threading.Lock()


def register_factor(spec: FactorSpec, user_id: str | None = None) -> None:
    """注册因子；重复 id 且版本未提升时报错（fail-closed）。

    user_id 为空 → 注册进全局 builtin 层（仅启动期 base 目录使用）；
    user_id 非空 → 注册进该用户的私有命名空间，对其他用户不可见。
    """
    with _LOCK:
        space = _REGISTRY if user_id is None else _USER_REGISTRIES.setdefault(user_id, {})
        existing = space.get(spec.id)
        if existing is not None and existing.version >= spec.version:
            raise ValueError(f"factor id 已注册且版本未提升: {spec.id}")
        space[spec.id] = spec


def get_factor(fid: str, user_id: str | None = None) -> FactorSpec | None:
    """取因子：先查 builtin 全局层，再查当前用户私有层（user_id 为空时只查全局）。"""
    with _LOCK:
        spec = _REGISTRY.get(fid)
        if spec is None and user_id is not None:
            spec = _USER_REGISTRIES.get(user_id, {}).get(fid)
        return spec


# 语义化别名：强调「builtin + 指定用户私有」合成视图，供 DSL 编译期解析用
def get_user_factor(fid: str, user_id: str | None) -> FactorSpec | None:
    return get_factor(fid, user_id)


def unregister_factor(fid: str, user_id: str | None = None) -> FactorSpec | None:
    """注销动态注册的因子；内置 base 因子不可注销（fail-closed）。

    user_id 非空时只注销该用户命名空间内的因子，不影响其他用户同名因子。
    """
    if fid in _CATALOG_IDS:
        raise ValueError(f"内置因子不可注销: {fid}")
    with _LOCK:
        space = _REGISTRY if user_id is None else _USER_REGISTRIES.get(user_id, {})
        return space.pop(fid, None)


def list_factors(kind: Kind | None = None, user_id: str | None = None) -> list[FactorSpec]:
    """列出因子：builtin 全局 + 当前用户私有（user_id 为空时仅 builtin）；
    kind 非空时按类型过滤。"""
    with _LOCK:
        specs = list(_REGISTRY.values())
        if user_id is not None:
            specs += list(_USER_REGISTRIES.get(user_id, {}).values())
    if kind is not None:
        specs = [s for s in specs if s.kind == kind]
    return specs


def factor_dependencies(fids, user_id: str | None = None) -> frozenset[str]:
    """把因子 id 列表展开到 base 列（矩阵物化层需要的输入列清单）。

    未知 id 原样保留（与参照历史语义一致）；base 因子依赖即自身。
    """
    with _LOCK:
        resolved: set[str] = set()
        for fid in fids:
            spec = _REGISTRY.get(str(fid))
            if spec is None and user_id is not None:
                spec = _USER_REGISTRIES.get(user_id, {}).get(str(fid))
            if spec is None:
                resolved.add(str(fid))
            elif spec.kind == "base":
                resolved.add(spec.id)
            elif spec.dependencies:
                resolved.update(spec.dependencies)
            else:
                resolved.add(spec.id)
    return frozenset(resolved)


def _register_base_catalog() -> None:
    for fid in OHLCV_COLUMNS + ENRICHED_INDICATORS:
        label, group, desc = _BASE_LABELS[fid]
        register_factor(FactorSpec(id=fid, label=label, group=group, formula_text=desc, kind="base"))
        _CATALOG_IDS.add(fid)


_register_base_catalog()
