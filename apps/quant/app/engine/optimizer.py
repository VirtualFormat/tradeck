"""参数网格搜索优化器（阶段 I3）。

给定策略 + 参数网格，遍历所有参数组合各跑一次回测（复用 runner.run_backtest），
按目标指标（objective）排序，返回最优参数与全部组合的排名表。

- spec 解析对齐 tick-stock-panel 参照实现：list / {"values": [...]} / {"min","max","step"}
  三种写法，逐值校验（min/max 边界、类型归一 int/float、step>0、整数计数生成候选
  避免浮点累加丢端点）。
- count_combinations 组合爆炸预判：超过 GRID_MAX_COMBINATIONS 直接拒绝。
- 敏感性分析 sensitivity()：固定其他参数，单参数扰动扫目标指标曲线。
- 优雅降级：单组回测异常隔离（记 error 排末位），绝不拖垮整批。

执行入口（同步 run_fn 注入 / 异步 run_optimize 走 worker 池）在 runner.py 接线。
"""
from __future__ import annotations

import itertools
import logging
import time
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable

logger = logging.getLogger(__name__)

# 组合数硬上限 —— 防止参数网格爆炸（每组一次回测，过大直接拒绝）。
GRID_MAX_COMBINATIONS = 2000

# 可选优化目标（须为 engine/stats.compute 输出中数值可比的字段）。
VALID_OBJECTIVES = {
    "total_return", "annual_return", "sharpe", "sortino", "calmar",
    "win_rate", "profit_loss_ratio", "turnover", "avg_hold_days",
    "trades", "days", "final_value", "max_drawdown",
}

# 需最小化的目标（值越小越好）；其余默认最大化。
# 注意：max_drawdown 为负值，最大化其带符号值 = 回撤越小越好，故仍归为 max。
_MINIMIZE_OBJECTIVES = {"turnover", "avg_hold_days"}


def _candidates_for(param_id: str, spec, pmeta: dict) -> list:
    """从 grid spec 解析某参数的候选值列表并逐个校验。

    spec 支持三种写法：
      - list: 显式候选值 [v1, v2, ...]
      - {"values": [...]}: 显式候选值
      - {"min", "max", "step"}: 数值型按步长展开（含端点）
    """
    p_type = pmeta.get("type", "float")

    # 解析原始候选值
    if isinstance(spec, list):
        raw = spec
    elif isinstance(spec, dict) and "values" in spec:
        raw = spec["values"]
    elif isinstance(spec, dict):
        if p_type not in ("float", "int"):
            raise ValueError(f"参数 '{param_id}' 为 {p_type} 型，不支持 min/max/step 展开，请给候选值列表")
        step = spec.get("step")
        if step is None:
            step = pmeta.get("step")
        if step is None or float(step) <= 0:
            raise ValueError(f"参数 '{param_id}' 的 step 必须为正数")
        lo = float(spec.get("min", pmeta.get("min", 0)))
        hi = float(spec.get("max", pmeta.get("max", 0)))
        if hi < lo:
            raise ValueError(f"参数 '{param_id}' 的 max < min")
        step = float(step)
        # 整数计数生成候选，避免浮点累加误差丢端点（如 0.1/0.1 步长）。
        # 步数向下取整：(hi-lo) 不是 step 整数倍时，四舍五入会多造一个越过 hi 的候选
        # （1~20 步长 7 → 22），用户填的上限反而被越界校验拒绝。1e-9 容差保住整除端点。
        n_steps = int((hi - lo) / step + 1e-9)
        raw = [round(lo + i * step, 10) for i in range(n_steps + 1)]
    else:
        raise ValueError(f"参数 '{param_id}' 的网格 spec 必须是列表或 {{min,max,step}} 字典")

    if not raw:
        raise ValueError(f"参数 '{param_id}' 的候选值为空")

    # 逐值校验 + 归一化类型
    out = []
    for val in raw:
        if p_type in ("float", "int"):
            try:
                num = float(val)
            except (TypeError, ValueError):
                raise ValueError(f"参数 '{param_id}' 的候选值 {val!r} 不是数字") from None
            if pmeta.get("min") is not None and num < float(pmeta["min"]) - 1e-9:
                raise ValueError(f"参数 '{param_id}' 的候选值 {val} 超出范围（< min {pmeta['min']}）")
            if pmeta.get("max") is not None and num > float(pmeta["max"]) + 1e-9:
                raise ValueError(f"参数 '{param_id}' 的候选值 {val} 超出范围（> max {pmeta['max']}）")
            out.append(round(num) if p_type == "int" else num)
        elif p_type == "bool":
            out.append(bool(val))
        elif p_type == "select":
            if val not in pmeta.get("options", []):
                raise ValueError(f"参数 '{param_id}' 的候选值 {val!r} 不在 options {pmeta.get('options')} 中")
            out.append(val)
        else:
            out.append(val)
    # 去重保序
    seen = set()
    uniq = []
    for v in out:
        k = (type(v).__name__, v)
        if k not in seen:
            seen.add(k)
            uniq.append(v)
    return uniq


def _grid_candidates(params_meta: list[dict], param_grid: dict) -> dict[str, list]:
    """校验整个 param_grid，返回 {param_id: [候选值...]}。"""
    if not param_grid:
        raise ValueError("参数网格为空，至少需要一个可扫参数")
    by_id = {p["id"]: p for p in params_meta}
    result: dict[str, list] = {}
    for pid, spec in param_grid.items():
        if pid not in by_id:
            raise ValueError(f"参数 '{pid}' 在该策略中不存在")
        result[pid] = _candidates_for(pid, spec, by_id[pid])
    return result


def count_combinations(params_meta: list[dict], param_grid: dict) -> int:
    """组合总数（笛卡尔积），用于爆炸预判。"""
    cands = _grid_candidates(params_meta, param_grid)
    total = 1
    for vals in cands.values():
        total *= len(vals)
    return total


def expand_param_grid(params_meta: list[dict], param_grid: dict) -> list[dict]:
    """校验并展开为参数组合列表，每个组合是 {param_id: value}（仅含被扫参数）。

    超过 GRID_MAX_COMBINATIONS 直接拒绝。
    """
    cands = _grid_candidates(params_meta, param_grid)
    total = 1
    for vals in cands.values():
        total *= len(vals)
    if total > GRID_MAX_COMBINATIONS:
        raise ValueError(f"参数组合数 {total} 超过上限 {GRID_MAX_COMBINATIONS}，请增大 step 或缩小范围")

    keys = list(cands.keys())
    combos = []
    for values in itertools.product(*(cands[k] for k in keys)):
        combos.append(dict(zip(keys, values, strict=True)))
    return combos


def default_direction(objective: str) -> str:
    """目标指标默认优化方向：min 类目标取 "min"，其余 "max"。"""
    return "min" if objective in _MINIMIZE_OBJECTIVES else "max"


def objective_value(stats: dict, objective: str, direction: str) -> float:
    """从 stats 提取目标值并转为「越大越好」的可比分数（None/缺失/nan/inf -> 最差）。"""
    raw = stats.get(objective)
    if raw is None:
        return float("-inf")
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return float("-inf")
    if v != v or v in (float("inf"), float("-inf")):  # nan/inf
        return float("-inf")
    return -v if direction == "min" else v


# 一次回测的同步执行函数签名（由 runner 注入：进程内 run_backtest 或
# 经 worker 池的同步包装）；返回 run_backtest 的结果 dict。
RunBacktestFn = Callable[..., dict]


@dataclass
class OptimizeConfig:
    """参数优化配置（与参照 OptimizeConfig 对齐，轻量化）。"""
    strategy_id: str
    symbols: list[str]
    start: date
    end: date
    param_grid: dict
    objective: str = "sharpe"
    direction: str | None = None          # None -> 由 objective 推断
    base_params: dict = field(default_factory=dict)  # 不扫的固定策略参数
    config: Any = None                    # MatcherConfig（撮合配置，透传）


def optimize(
    cfg: OptimizeConfig,
    params_meta: list[dict],
    run_fn: RunBacktestFn,
    progress_cb=None,
) -> dict:
    """串行遍历参数组合跑回测，按目标排序，返回最优参数 + 排名表。

    run_fn(symbols, strategy_id, start, end, params, config) -> dict（run_backtest 结果）。
    单组异常隔离：记 error 排末位，不拖垮整批。
    """
    t0 = time.perf_counter()
    if cfg.objective not in VALID_OBJECTIVES:
        raise ValueError(f"不支持的优化目标 '{cfg.objective}'，可选：{sorted(VALID_OBJECTIVES)}")
    direction = cfg.direction or default_direction(cfg.objective)
    combos = expand_param_grid(params_meta, cfg.param_grid)
    n_total = len(combos)

    results: list[dict] = []
    for done, combo in enumerate(combos, start=1):
        params = {**cfg.base_params, **combo}
        # 单组异常必须隔离：一组失败不能丢弃全部已完成结果
        try:
            res = run_fn(cfg.symbols, cfg.strategy_id, cfg.start, cfg.end,
                         params=params, config=cfg.config)
            stats = res.get("stats") or {}
            if cfg.objective not in stats:
                raise ValueError(f"回测结果缺少优化目标字段 '{cfg.objective}'")
            row = {
                "params": combo,
                "objective_raw": stats.get(cfg.objective),
                "_sort": objective_value(stats, cfg.objective, direction),
                "stats": stats,
            }
        except Exception as e:  # 隔离单组失败，记录后继续
            logger.warning("参数组 %s 回测异常：%r", combo, e)
            row = {"params": combo, "error": repr(e), "objective_raw": None,
                   "_sort": float("-inf")}
        results.append(row)
        if progress_cb is not None:
            valid = [r for r in results if r["_sort"] != float("-inf")]
            best_so_far = max(valid, key=lambda x: x["_sort"])["objective_raw"] if valid else None
            progress_cb({
                "type": "optimizer_progress",
                "done": done,
                "total": n_total,
                "best_score": round(best_so_far, 4) if best_so_far is not None else None,
            })

    ranked = sorted(results, key=lambda x: x["_sort"], reverse=True)
    for i, row in enumerate(ranked):
        row["rank"] = i + 1
        row.pop("_sort", None)

    best = ranked[0] if ranked and ranked[0].get("objective_raw") is not None else None
    best_raw = best["objective_raw"] if best else None
    return {
        "strategy": cfg.strategy_id,
        "symbols": cfg.symbols,
        "range": [cfg.start.isoformat(), cfg.end.isoformat()],
        "objective": cfg.objective,
        "direction": direction,
        "n_combinations": n_total,
        "n_completed": len(results),
        "n_errors": sum(1 for r in ranked if r.get("error")),
        "best_params": best["params"] if best else None,
        "best_score": round(best_raw, 4) if best_raw is not None else None,
        "results": ranked,
        "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1),
    }


def sensitivity(
    cfg: OptimizeConfig,
    params_meta: list[dict],
    run_fn: RunBacktestFn,
    param_id: str,
    progress_cb=None,
) -> dict:
    """敏感性分析：固定其他参数（base_params + META 默认值），单参数扰动扫目标指标曲线。

    cfg.param_grid 只取 param_id 一项的 spec；base_params 提供其余参数的固定值。
    """
    if param_id not in cfg.param_grid:
        raise ValueError(f"敏感性分析需要在 param_grid 中提供 '{param_id}' 的 spec")
    t0 = time.perf_counter()
    if cfg.objective not in VALID_OBJECTIVES:
        raise ValueError(f"不支持的优化目标 '{cfg.objective}'，可选：{sorted(VALID_OBJECTIVES)}")
    direction = cfg.direction or default_direction(cfg.objective)
    by_id = {p["id"]: p for p in params_meta}
    if param_id not in by_id:
        raise ValueError(f"参数 '{param_id}' 在该策略中不存在")

    cands = _candidates_for(param_id, cfg.param_grid[param_id], by_id[param_id])
    # 其余参数默认值：base_params 优先，缺省回退 META default
    fixed = {p["id"]: p.get("default") for p in params_meta}
    fixed.update(cfg.base_params)
    fixed.pop(param_id, None)

    points: list[dict] = []
    for done, val in enumerate(cands, start=1):
        params = {**fixed, param_id: val}
        try:
            res = run_fn(cfg.symbols, cfg.strategy_id, cfg.start, cfg.end,
                         params=params, config=cfg.config)
            stats = res.get("stats") or {}
            point = {
                "value": val,
                "objective_raw": stats.get(cfg.objective),
                "_sort": objective_value(stats, cfg.objective, direction),
                "stats": stats,
            }
        except Exception as e:  # 单点失败隔离，记 error
            logger.warning("敏感性参数组 %s=%s 回测异常：%r", param_id, val, e)
            point = {"value": val, "error": repr(e), "objective_raw": None,
                     "_sort": float("-inf")}
        points.append(point)
        if progress_cb is not None:
            progress_cb({"type": "sensitivity_progress", "done": done, "total": len(cands)})

    for p in points:
        p.pop("_sort", None)
    valid = [p for p in points if p.get("objective_raw") is not None]
    best_point = max(
        valid,
        key=lambda x: objective_value({cfg.objective: x["objective_raw"]},
                                      cfg.objective, direction),
    ) if valid else None
    return {
        "strategy": cfg.strategy_id,
        "symbols": cfg.symbols,
        "range": [cfg.start.isoformat(), cfg.end.isoformat()],
        "objective": cfg.objective,
        "direction": direction,
        "param_id": param_id,
        "fixed_params": fixed,
        "points": points,
        "best_value": best_point["value"] if best_point else None,
        "best_score": round(best_point["objective_raw"], 4) if best_point else None,
        "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1),
    }
