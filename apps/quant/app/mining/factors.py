"""因子目录 — 从 enriched 矩阵派生可挖掘的日频因子。

每个因子一个 (dates × symbols) 数组（与矩阵同形状，NaN 传播）。
V1 边界（对齐参照 mining.md）：只用本地日频数据派生的价量/形态/流动性因子，
不生成任意公式、不用分钟数据、不接扩展数据源。财务因子走 data-api as-of（另议）。

时点红线：因子在 T 日的值只能用 T 日及之前的数据（动量/波动/极值天然满足；
收益形态类用 rolling 窗口，窗口右端含当日）。
"""
from __future__ import annotations

import logging

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

from app.matrix import EnrichedMatrix

logger = logging.getLogger(__name__)


def _shift(arr: np.ndarray, n: int) -> np.ndarray:
    """沿时间轴下移 n 行（前 n 行 NaN）。"""
    out = np.full(arr.shape, np.nan)
    if arr.shape[0] > n:
        out[n:] = arr[:-n]
    return out


def _rolling(arr: np.ndarray, n: int, fn) -> np.ndarray:
    """窗口聚合（窗口内任一 NaN 则该期 NaN，预热期 NaN）。"""
    out = np.full(arr.shape, np.nan)
    if arr.shape[0] < n:
        return out
    w = sliding_window_view(arr, n, axis=0)
    valid = ~np.isnan(w).any(axis=2)
    res = np.where(valid, fn(w, axis=2), np.nan)
    out[n - 1 :] = res
    return out


def _daily_ret(close: np.ndarray) -> np.ndarray:
    """日收益率（小数），首行与跨停牌为 NaN。"""
    prev = _shift(close, 1)
    return np.where(np.isnan(prev) | np.isnan(close), np.nan, close / prev - 1.0)


def _safe_eval(arr: np.ndarray | None, shape: tuple[int, int]) -> np.ndarray | None:
    """求值结果健康检查：形状不符 / 全 NaN（无有效截面）返回 None（跳过，优雅降级）。"""
    if arr is None:
        return None
    arr = np.asarray(arr, dtype=np.float64)
    if arr.shape != shape or not np.isfinite(arr).any():
        return None
    return arr


def _cross_zscore(arr: np.ndarray) -> np.ndarray:
    """当日截面 zscore（沿 symbols 轴；有效数 <2 或截面零方差时为 NaN）。"""
    n = np.isfinite(arr).sum(axis=1, keepdims=True)
    mean = np.nanmean(arr, axis=1, keepdims=True)
    std = np.nanstd(arr, axis=1, keepdims=True)
    ok = (n >= 2) & (std > 0)
    return np.where(ok, (arr - mean) / np.where(std > 0, std, np.nan), np.nan)


def _evaluate_user_factor(spec, enriched: EnrichedMatrix, user_id: str) -> np.ndarray | None:
    """对单个 active 用户因子求值，返回 (dates × symbols) 或 None（跳过）。

    对注入矩阵只读：uf_*（DSL 因子）经 compile_formula 编译产物的 evaluate()
    求值（编译失败/求值异常/缺列时 evaluate 返回 None，优雅降级跳过）；
    cf_*（复合因子）不重新编译——直接取成员（base 列或 uf_*）值做当日截面
    zscore 后按权重加权合成（简单可靠；成员缺失/全 NaN 按 0 权重跳过，
    剩余成员权重归一，全部成员不可用则整体跳过）。
    """
    shape = enriched.base.shape
    if spec.kind == "composite":
        total_w = 0.0
        acc = np.full(shape, 0.0)
        from app.factors import registry as _reg
        for member_id, weight in spec.components:
            member = _reg.get_factor(member_id, user_id)
            if member is None or member.kind == "composite":
                continue  # 复合成员不再递归展开（二级嵌套少见，防深递归）
            vals = (
                _evaluate_user_factor(member, enriched, user_id)
                if member.kind == "custom"
                else _safe_eval(_default_get_col(enriched)(member_id), shape)
            )
            if vals is None:
                continue
            acc = acc + weight * np.where(np.isnan(_cross_zscore(vals)), 0.0, _cross_zscore(vals))
            total_w += abs(weight)
        if total_w <= 0:
            return None
        return _safe_eval(acc / total_w, shape)
    compiled = _compile_cached(spec.id, spec.formula_text, spec.version, user_id)
    if not compiled.ok:
        logger.warning("用户因子 %s 编译失败，挖掘目录跳过：%s",
                       spec.id, compiled.errors[0].message if compiled.errors else "?")
        return None
    return _safe_eval(compiled.evaluate(enriched), shape)


# 编译产物缓存（review P2 修复）：避免每次回测/选股请求对每个用户因子重新
# tokenizer+parser+编译。键含 (user_id, factor_id, version, formula)——公式或
# 版本变更自动失效（version+1 进键），用户隔离。模块级字典，quant 单进程内安全。
_COMPILE_CACHE: dict[tuple, object] = {}


def _compile_cached(factor_id: str, formula: str, version: int, user_id: str):
    from app.factors.dsl import compile_formula
    key = (user_id, factor_id, version, formula)
    if key not in _COMPILE_CACHE:
        _COMPILE_CACHE[key] = compile_formula(formula, user_id=user_id)
    return _COMPILE_CACHE[key]


def _default_get_col(matrix: EnrichedMatrix):
    """base 列取数器（OHLCV 基准列 + enriched 指标列）。"""
    def _get(name: str) -> np.ndarray:
        from app.matrix.market import FIELDS
        if name in FIELDS:
            return np.asarray(getattr(matrix.base, name), dtype=np.float64)
        return np.asarray(matrix.indicators[name], dtype=np.float64)
    return _get


def active_user_factors(user_id: str) -> list:
    """当前用户 active 状态的 uf_*/cf_* 因子 spec 列表（draft/watch/retired 不进目录）。

    状态从 store 落盘定义读（注册表 spec 不含 status）；先把该用户磁盘上的因子
    重放进其私有命名空间（幂等），再取注册表「builtin + 本人私有」视图过滤。
    """
    from app.factors import registry, store
    store.load_into_registry(user_id)
    statuses = {
        str(d["id"]): str(d.get("status", store.STATUS_DRAFT))
        for d in store.load_all(user_id)
        if d.get("id")
    }
    return [
        spec for spec in registry.list_factors(user_id=user_id)
        if spec.kind in ("custom", "composite")
        and statuses.get(spec.id) == store.STATUS_ACTIVE
    ]


def user_factor_meta(user_id: str) -> dict[str, tuple[str, int]]:
    """用户 active 因子的挖掘目录元信息 {id: (中文说明, 预期方向)}（动态，不入 FACTOR_META）。"""
    meta: dict[str, tuple[str, int]] = {}
    for spec in active_user_factors(user_id):
        label = spec.label or spec.id
        group = f"[{spec.group}] " if spec.group else ""
        direction = {"high": 1, "low": -1}.get(spec.direction, 1)
        meta[spec.id] = (f"{group}{label}", direction)
    return meta


def factor_catalog(enriched: EnrichedMatrix, user_id: str | None = None) -> dict[str, np.ndarray]:
    """派生全部可挖掘因子，返回 {因子名: (dates × symbols)}。

    分四类（命名即口径，注释标注金融含义与预期方向）：
    """
    base = enriched.base
    close, volume, amount = base.close, base.volume, base.amount
    ind = enriched.indicators
    ret = _daily_ret(close)

    factors: dict[str, np.ndarray] = {}

    # ── 动量/趋势（已有指标直接复用 + 派生）──────────────────
    factors["momentum_5d"] = ind["momentum_5d"]      # 5 日动量（小数）
    factors["momentum_20d"] = ind["momentum_20d"]    # 20 日动量
    # 均线偏离：收盘价相对均线的偏离度（趋势强度，正向）
    for p in (5, 10, 20, 60):
        ma = ind[f"ma{p}"]
        factors[f"ma{p}_bias"] = np.where(
            np.isnan(ma) | (ma == 0), np.nan, close / ma - 1.0
        )

    # ── 波动率（反向：低波动异象）───────────────────────────
    factors["volatility_20d"] = _rolling(ret, 20, lambda w, axis: w.std(axis=axis))

    # ── 收益形态（A 股实证维度）─────────────────────────────
    # 彩票效应：20 日最大单日涨幅（正向偏好彩票型，实证上未来收益反而低 → 反向候选）
    factors["max_ret_20d"] = _rolling(ret, 20, lambda w, axis: w.max(axis=axis))
    # 收益偏度：20 日收益分布偏度（右偏=彩票型）
    factors["ret_skew_20d"] = _rolling(ret, 20, lambda w, axis: _skew(w, axis))
    # 上涨天数占比：20 日内收阳比例（趋势持续性）
    up = np.where(np.isnan(ret), np.nan, (ret > 0).astype(float))
    factors["up_days_20d"] = _rolling(up, 20, lambda w, axis: w.mean(axis=axis))

    # ── 流动性（反向：低流动性溢价 / 换手异动）──────────────
    # Amihud 非流动性：|收益| / 成交额（值越大流动性越差，实证正向溢价）
    illiq = np.where(
        np.isnan(ret) | np.isnan(amount) | (amount == 0), np.nan,
        np.abs(ret) / (amount / 1e8),  # 成交额归一到亿，避免数值过小
    )
    factors["amihud_20d"] = _rolling(illiq, 20, lambda w, axis: w.mean(axis=axis))
    # 量比（短期换手异动）
    factors["vol_ratio_5d"] = ind["vol_ratio_5d"]

    # ── 超买超卖（反转）────────────────────────────────────
    factors["rsi14"] = ind["rsi14"]                  # 高=超买（反向）
    # 距 20 日高点距离（突破/乖离）
    h20 = ind["high_20d"]
    factors["dist_to_high_20d"] = np.where(
        np.isnan(h20) | (h20 == 0), np.nan, close / h20 - 1.0
    )

    # ── 用户因子（阶段 K6）：当前用户 active 状态的 uf_*/cf_* 与内置因子同等待遇
    # 纳入目录（参与 IC/去重/组合搜索）；求值失败/全 NaN 逐个跳过（优雅降级），
    # 绝不让单个坏因子拖垮挖掘。user_id 为空时与现状一致（仅内置 14 因子）。
    if user_id:
        for spec in active_user_factors(user_id):
            if spec.id in factors:
                continue  # 内置同名占位（uf_/cf_ 前缀天然不会撞，防御性保留）
            try:
                vals = _evaluate_user_factor(spec, enriched, user_id)
            except Exception as e:  # 防御性兜底：求值路径不应抛，但绝不波及其他因子
                logger.warning("用户因子 %s 求值异常，挖掘目录跳过：%s", spec.id, e)
                continue
            if vals is None:
                logger.info("用户因子 %s 求值失败/全 NaN，挖掘目录跳过", spec.id)
                continue
            factors[spec.id] = vals

    return factors


def _skew(w: np.ndarray, axis: int) -> np.ndarray:
    """窗口偏度（Fisher，ddof=0），常数窗口返回 0。"""
    mean = w.mean(axis=axis, keepdims=True)
    dev = w - mean
    m3 = (dev ** 3).mean(axis=axis)
    m2 = (dev ** 2).mean(axis=axis)
    std = np.sqrt(m2)
    return np.where(std > 0, m3 / (std ** 3 + 1e-12), 0.0)


# 因子元信息：{因子名: (中文说明, 预期方向)}，direction: 1=正向（值大未来涨）, -1=反向
# 预期方向仅作展示与方向自动判定的参考，实际方向由训练折 RankIC 符号决定（见 mining/core）。
FACTOR_META: dict[str, tuple[str, int]] = {
    "momentum_5d": ("5 日动量", 1),
    "momentum_20d": ("20 日动量", 1),
    "ma5_bias": ("MA5 偏离", 1),
    "ma10_bias": ("MA10 偏离", 1),
    "ma20_bias": ("MA20 偏离", 1),
    "ma60_bias": ("MA60 偏离", 1),
    "volatility_20d": ("20 日波动率", -1),
    "max_ret_20d": ("20 日最大单日涨幅（彩票）", -1),
    "ret_skew_20d": ("20 日收益偏度", -1),
    "up_days_20d": ("20 日上涨天数占比", 1),
    "amihud_20d": ("Amihud 非流动性", 1),
    "vol_ratio_5d": ("量比（5 日）", 1),
    "rsi14": ("RSI14（超买超卖）", -1),
    "dist_to_high_20d": ("距 20 日高点距离", 1),
}
