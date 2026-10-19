"""回测结果裁剪：原始结果含逐日净值、逐笔交易、数百标的统计，整包会撑爆 agent 上下文。

字段口径对齐 apps/quant/app/runner.py：
- run_backtest（组合模拟）：stats / strategy / symbols / range / unadjusted / trades / equity_curve /
  benchmark / minute_fill_used / minute_fill_fallback / execution_stats / per_symbol_stats /
  return_distribution / daily_trade_rows / selection_stats / factor_attribution / run_id / elapsed_ms。
- run_backtest_full（全量模拟）：同上骨架，stats 为样本口径（mode="full"，内嵌 per_symbol_stats /
  return_distribution 列表）。
- 分钟回放（mode="minute_replay"）：replayed_days / skipped_days / buy_limit_up / hits，无 trades/equity。

summary：策略/区间/标量 stats/执行统计/基准/降采样净值（≤50 点，保留首尾）/per_symbol 最好最差各 10/
交易笔数/unadjusted 数量与前 20；序列化后保证 ≤ SUMMARY_MAX_BYTES（超限逐级收缩）。
分页：trades / per_symbol / equity 返回 {total, offset, limit, items}。
"""

from __future__ import annotations

import json
from typing import Any

# 摘要体积预算：工具输出 = 任务字段（~300B）+ 摘要，整体须 ≤10KB，摘要本身留 1KB 余量
SUMMARY_MAX_BYTES = 9 * 1024
SECTIONS = ("summary", "trades", "per_symbol", "equity")

# 标识类字符串（策略 id / 标的代码 / stats 内的 mode 等）上限：策略 id 本身 ≤64，不截断
_ID_LIMIT = 64
# 逐级收缩档位：首两档即契约口径（净值 50 点 / per_symbol 最好最差各 10 / unadjusted 前 20），
# 超预算时先收行内文本（超长证券名称等，"str"）与卖出归因，仍超才减条数
_LEVELS = (
    {
        "equity": 50,
        "per_symbol": 10,
        "unadjusted": 20,
        "hits": 10,
        "str": 40,
        "exit_stats": True,
    },
    {
        "equity": 50,
        "per_symbol": 10,
        "unadjusted": 20,
        "hits": 10,
        "str": 16,
        "exit_stats": False,
    },
    {
        "equity": 30,
        "per_symbol": 5,
        "unadjusted": 10,
        "hits": 5,
        "str": 16,
        "exit_stats": False,
    },
    {
        "equity": 12,
        "per_symbol": 3,
        "unadjusted": 5,
        "hits": 3,
        "str": 16,
        "exit_stats": False,
    },
    {
        "equity": 2,
        "per_symbol": 0,
        "unadjusted": 0,
        "hits": 0,
        "str": 16,
        "exit_stats": False,
    },
)

_SECTION_FIELDS = {
    "trades": "trades",
    "per_symbol": "per_symbol_stats",
    "equity": "equity_curve",
}


def dumps(obj: Any) -> str:
    """紧凑 JSON（中文不转义）：工具文本输出与体积测量同一口径。"""
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), default=str)


def _round(v: Any) -> Any:
    """浮点保留 6 位（净值/收益率展示足够，显著压缩体积）。"""
    if isinstance(v, float):
        return round(v, 6)
    return v


def _is_scalar(v: Any) -> bool:
    return v is None or isinstance(v, (bool, int, float, str))


def _clip_str(v: Any, limit: int) -> Any:
    if isinstance(v, str) and len(v) > limit:
        return v[:limit] + "…"
    return v


def downsample(points: list, max_points: int) -> list:
    """等距降采样到 ≤ max_points，保留首尾（max_points < 2 时只留首尾）。"""
    n = len(points)
    if n <= max_points:
        return list(points)
    if max_points <= 2:
        return [points[0], points[-1]]
    step = (n - 1) / (max_points - 1)
    idx = sorted({round(i * step) for i in range(max_points)} | {0, n - 1})
    return [points[i] for i in idx]


def _per_symbol_rows(result: dict) -> list:
    rows = result.get("per_symbol_stats")
    if not isinstance(rows, list):
        stats = result.get("stats")
        rows = stats.get("per_symbol_stats") if isinstance(stats, dict) else None
    return rows if isinstance(rows, list) else []


def _best_worst(rows: list, k: int, str_limit: int) -> dict:
    """per_symbol 按 total_return 取最好/最差各 k（不重叠；quant 侧已降序，这里再排一次防御）。"""
    if k <= 0 or not rows:
        return {"total": len(rows), "best": [], "worst": []}
    valid = [r for r in rows if isinstance(r, dict)]
    ordered = sorted(
        valid,
        key=lambda r: (
            r.get("total_return")
            if isinstance(r.get("total_return"), (int, float))
            else float("-inf")
        ),
        reverse=True,
    )
    best = ordered[:k]
    worst = ordered[max(k, len(ordered) - k) :][::-1]

    def slim(r: dict) -> dict:
        # symbol 是后续分页/复查的锚点，按标识口径保留；name 等行内文本按档位截断
        return {
            key: _clip_str(_round(val), _ID_LIMIT if key == "symbol" else str_limit)
            for key, val in r.items()
            if _is_scalar(val)
        }

    return {
        "total": len(rows),
        "best": [slim(r) for r in best],
        "worst": [slim(r) for r in worst],
    }


def _scalar_stats(stats: Any, str_limit: int) -> dict:
    if not isinstance(stats, dict):
        return {}
    return {
        k: _clip_str(_round(v), str_limit) for k, v in stats.items() if _is_scalar(v)
    }


def _small_dict(d: Any, str_limit: int, max_keys: int = 20) -> dict | None:
    """小型 dict（execution_stats / selection_stats / benchmark）只留标量键，限键数。"""
    if not isinstance(d, dict):
        return None
    items = [(k, v) for k, v in d.items() if _is_scalar(v)][:max_keys]
    return {str(k): _clip_str(_round(v), str_limit) for k, v in items}


def _exit_stats(stats: Any, str_limit: int, max_keys: int = 12) -> dict | None:
    """卖出归因（stats.exit_stats：reason → {count, win_rate, total_pnl, avg_pnl}），键数有界。"""
    es = stats.get("exit_stats") if isinstance(stats, dict) else None
    if not isinstance(es, dict):
        return None
    out = {}
    for reason, row in list(es.items())[:max_keys]:
        if isinstance(row, dict):
            out[_clip_str(str(reason), str_limit)] = {
                k: _round(v) for k, v in row.items() if _is_scalar(v)
            }
    return out


def _equity_points(curve: Any, max_points: int) -> list:
    if not isinstance(curve, list):
        return []
    pts = downsample(curve, max_points)
    out = []
    for p in pts:
        if isinstance(p, dict):
            out.append({k: _round(v) for k, v in p.items() if _is_scalar(v)})
    return out


def _build_summary(result: dict, level: dict) -> dict:
    str_limit = level["str"]
    stats = result.get("stats")
    unadjusted = (
        result.get("unadjusted") if isinstance(result.get("unadjusted"), list) else []
    )
    symbols = result.get("symbols") if isinstance(result.get("symbols"), list) else []
    out: dict[str, Any] = {
        "strategy": _clip_str(result.get("strategy"), _ID_LIMIT),
        "range": result.get("range"),
        "symbol_count": len(symbols),
    }
    mode = result.get("mode") or (
        stats.get("mode") if isinstance(stats, dict) else None
    )
    if mode:
        out["mode"] = mode
    if result.get("error"):
        out["error"] = _clip_str(str(result["error"]), max(str_limit, 500))

    if mode == "minute_replay":
        hits = result.get("hits") if isinstance(result.get("hits"), list) else []
        skipped = (
            result.get("skipped_days")
            if isinstance(result.get("skipped_days"), list)
            else []
        )
        out.update(
            {
                "replayed_days": result.get("replayed_days"),
                "skipped_day_count": len(skipped),
                "buy_limit_up": result.get("buy_limit_up"),
                "hit_count": len(hits),
                "hits_head": [
                    {
                        k: _clip_str(_round(v), str_limit)
                        for k, v in h.items()
                        if _is_scalar(v)
                    }
                    for h in hits[: level["hits"]]
                    if isinstance(h, dict)
                ],
            }
        )
    else:
        out["stats"] = _scalar_stats(stats, _ID_LIMIT)
        exit_stats = _exit_stats(stats, _ID_LIMIT) if level["exit_stats"] else None
        if exit_stats:
            out["exit_stats"] = exit_stats
        trades = result.get("trades") if isinstance(result.get("trades"), list) else []
        out["trade_count"] = len(trades)
        for key in ("execution_stats", "selection_stats", "benchmark"):
            d = _small_dict(result.get(key), _ID_LIMIT)
            if d is not None:
                out[key] = d
        for key in ("minute_fill_used", "minute_fill_fallback"):
            if _is_scalar(result.get(key)) and result.get(key) is not None:
                out[key] = result[key]
        curve = result.get("equity_curve")
        out["equity_curve_total"] = len(curve) if isinstance(curve, list) else 0
        out["equity_curve"] = _equity_points(curve, level["equity"])
        out["per_symbol"] = _best_worst(
            _per_symbol_rows(result), level["per_symbol"], str_limit
        )

    out["unadjusted_count"] = len(unadjusted)
    out["unadjusted_head"] = [
        _clip_str(s, _ID_LIMIT) for s in unadjusted[: level["unadjusted"]]
    ]
    out["more"] = "完整明细用 section=trades|per_symbol|equity 分页获取"
    return out


def summarize(result: Any) -> dict:
    """结果摘要：逐级收缩直到紧凑 JSON ≤ SUMMARY_MAX_BYTES。"""
    if not isinstance(result, dict):
        return {"error": "回测结果结构异常"}
    for level in _LEVELS:
        summary = _build_summary(result, level)
        if len(dumps(summary).encode("utf-8")) <= SUMMARY_MAX_BYTES:
            return summary
    # 兜底（理论不可达：最小档只剩有界标量）：只留核心标量
    stats = _scalar_stats(result.get("stats"), _ID_LIMIT)
    keep = {k: stats[k] for k in list(stats)[:30]}
    return {
        "strategy": _clip_str(result.get("strategy"), _ID_LIMIT),
        "range": result.get("range"),
        "stats": keep,
        "truncated": True,
    }


def section_items(result: Any, section: str) -> list:
    """分页源数据；分钟回放的 trades 映射到 hits（该模式无逐笔交易）。"""
    if not isinstance(result, dict):
        return []
    if section == "trades" and result.get("mode") == "minute_replay":
        rows = result.get("hits")
    elif section == "per_symbol":
        rows = _per_symbol_rows(result)
    else:
        rows = result.get(_SECTION_FIELDS[section])
    return rows if isinstance(rows, list) else []


def paginate(rows: list, offset: int, limit: int) -> dict:
    return {
        "total": len(rows),
        "offset": offset,
        "limit": limit,
        "items": rows[offset : offset + limit],
    }
