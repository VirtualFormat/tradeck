"""因子挖掘运行时 — 把核心算法串成完整流程 + 候选库持久化（发布纪律是铁律）。

流程（对齐参照 mining.md 闭环，V1 边界内）：
1. 训练区间重算因子方向（RankIC 符号）与统计。
2. 截面 Rank 相关去重（保强剔弱）。
3. beam 搜索 ≤4 因子受控组合。
4. 嵌套样本外验证比较组合；已有策略作对照轨独立评估，不参与因子竞争。
5. 运行持久化（可重连）；候选入候选库——显式确认且过门槛才发布，永不自动上线。

候选库：{cache}/users/{uid}/mining/candidates.parquet（status: pending/published/rejected，
多用户骨架 G4：按用户命名空间隔离，默认 default）。
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np
import polars as pl

from app.config import settings
from app.matrix import EnrichedMatrix
from app.mining import core
from app.mining.factors import FACTOR_META, factor_catalog

logger = logging.getLogger(__name__)


@dataclass
class MiningRunResult:
    """一次挖掘运行的产出（摘要 + 候选）。"""
    n_factors: int
    kept_factors: list[str]
    dropped: list[tuple[str, str]]
    factor_ics: dict[str, float]
    candidates: list[core.CandidateResult]
    n_folds: int


def _slice(arr: np.ndarray, start: int, end: int) -> np.ndarray:
    return arr[start:end]


def _backtest_top_n(
    factor_score: np.ndarray, close: np.ndarray, top_n: int = 5
) -> tuple[float, float, float, int]:
    """极简多头回测：每日持因子分最高的 top_n 只（等权），返回 (夏普, 总收益, 最大回撤, 交易数)。

    这是样本外评估的轻量口径（不跑完整撮合，用日收益近似），用于挖掘期快速比较。
    交易数 = 调仓次数（每日换手持仓数变化）。
    """
    n_days, n_syms = factor_score.shape
    ret = np.full(close.shape, np.nan)
    ret[1:] = np.where(
        np.isnan(close[1:]) | np.isnan(close[:-1]), np.nan, close[1:] / close[:-1] - 1.0
    )
    daily_port = []
    trades = 0
    prev_holdings: set[int] = set()
    for t in range(n_days):
        row = factor_score[t]
        valid = ~np.isnan(row)
        if valid.sum() < top_n:
            daily_port.append(np.nan)
            continue
        top_idx = np.argsort(np.where(valid, row, -np.inf))[-top_n:]
        holdings = set(int(i) for i in top_idx)
        trades += len(holdings.symmetric_difference(prev_holdings))
        prev_holdings = holdings
        vals = ret[t, list(holdings)] if holdings else np.array([])
        valid_vals = vals[~np.isnan(vals)]
        day_ret = float(valid_vals.mean()) if valid_vals.size else np.nan
        daily_port.append(day_ret)
    eq = np.array([r for r in daily_port if not np.isnan(r)])
    if len(eq) < 5:
        return np.nan, 0.0, 0.0, 0
    sharpe = float(eq.mean() / eq.std() * np.sqrt(252)) if eq.std() > 0 else 0.0
    total = float((1 + eq).prod() - 1)
    curve = np.cumprod(1 + eq)
    max_dd = float((curve / np.maximum.accumulate(curve) - 1).min())
    return sharpe, total, max_dd, trades


def run_mining(
    enriched: EnrichedMatrix,
    horizon: int = 5,
    max_size: int = 4,
    beam_width: int = 16,
    n_outer: int = 3,
    top_n: int = 5,
) -> MiningRunResult:
    """对一批标的跑完整因子挖掘，返回候选（含嵌套样本外评估）。

    enriched：复权后的市场矩阵（含指标）。horizon：预测未来 N 日收益。
    """
    close = enriched.base.close
    n_days = close.shape[0]
    factors = factor_catalog(enriched)
    fwd = core.forward_returns(close, horizon)

    # 1. 全样本因子 IC（方向由符号定）——仅用于展示，嵌套折内会重算
    full_ics = {}
    full_dirs = {}
    for name, f in factors.items():
        ic, _, _ = core.factor_rank_ic(f, fwd)
        if not np.isnan(ic):
            full_ics[name] = ic
            full_dirs[name] = 1 if ic >= 0 else -1

    # 2. 嵌套样本外：每个 outer 折在训练段选因子/搜组合，测试段独立评估
    folds = core.make_nested_folds(n_days, n_outer=n_outer)
    if not folds:
        logger.warning("天数 %d 不足以切嵌套折，返回空候选", n_days)
        return MiningRunResult(0, [], [], {}, [], 0)

    # 用第一折训练段做全局去重与搜索的「代表性候选集」（各折独立评估时复用同一候选池，
    # 严格做法是每折独立搜索，但候选池共享可大幅降本，且样本外评估仍保独立——权衡取舍）
    first = folds[0]
    train_ics, train_dirs = {}, {}
    for name, f in factors.items():
        ic, _, _ = core.factor_rank_ic(
            _slice(f, first.train_start, first.train_end),
            _slice(fwd, first.train_start, first.train_end),
        )
        if not np.isnan(ic):
            train_ics[name] = ic
            train_dirs[name] = 1 if ic >= 0 else -1

    # 3. 去重（训练段相关）
    train_factors = {n: _slice(f, first.train_start, first.train_end) for n, f in factors.items() if n in train_ics}
    corr = core.factor_correlation(train_factors)
    kept, dropped = core.prune_correlated(train_ics, corr, threshold=0.7)

    # 4. beam 搜索（训练段）
    kept_factors_train = {n: train_factors[n] for n in kept}
    kept_fwd_train = _slice(fwd, first.train_start, first.train_end)
    # 候选池必须是去重后的子集（否则 combine_factors 在合成时取不到被剔因子）
    kept_ics = {n: train_ics[n] for n in kept}
    combos = core.beam_search(
        kept_factors_train, kept_fwd_train, kept_ics, train_dirs,
        max_size=max_size, beam_width=beam_width, correlation=corr,
    )
    # 取 top 候选（单因子 + 多因子混合，上限 8 控评估成本）
    candidates = combos[:8]

    # 5. 嵌套样本外评估每个候选
    results: list[core.CandidateResult] = []
    for combo, _ in candidates:
        cr = core.CandidateResult(combo=combo, directions={n: train_dirs[n] for n in combo})
        for k, fold in enumerate(folds):
            test_score = core.combine_factors(
                {n: _slice(factors[n], fold.test_start, fold.test_end) for n in combo},
                combo, cr.directions,
            )
            test_close = _slice(close, fold.test_start, fold.test_end)
            sharpe, total, max_dd, trades = _backtest_top_n(test_score, test_close, top_n)
            if np.isnan(sharpe):
                continue
            cr.folds.append(core.FoldResult(
                fold_index=k, combo=combo, oos_sharpe=sharpe, oos_return=total,
                oos_max_drawdown=max_dd, oos_trades=trades, oos_positive=total > 0,
            ))
        results.append(cr)

    return MiningRunResult(
        n_factors=len(factors), kept_factors=kept, dropped=dropped,
        factor_ics=full_ics, candidates=results, n_folds=len(folds),
    )


# ---------------------------------------------------------------------------
# 候选库（发布纪律：显式确认 + 过门槛才发布，永不自动上线）
# ---------------------------------------------------------------------------

_CANDIDATES_SCHEMA = {
    "candidate_id": pl.String, "combo": pl.String, "directions": pl.String,
    "status": pl.String, "oos_sharpe": pl.Float64, "oos_max_drawdown": pl.Float64,
    "oos_trades": pl.Int64, "valid_folds": pl.Int64, "positive_fold_ratio": pl.Float64,
    "gate_reasons": pl.String, "created_at": pl.String, "published_at": pl.String,
}


def _candidates_file(user_id: str | None = None) -> Path:
    """候选库路径（用户命名空间隔离；缺省回落 QUANT_DEFAULT_USER）。"""
    uid = user_id or settings.QUANT_DEFAULT_USER
    return Path(settings.QUANT_CACHE_DIR) / "users" / uid / "mining" / "candidates.parquet"


def load_candidates(user_id: str | None = None) -> pl.DataFrame:
    f = _candidates_file(user_id)
    if not f.exists():
        return pl.DataFrame(schema=_CANDIDATES_SCHEMA)
    try:
        return pl.read_parquet(f)
    except Exception as e:
        logger.warning("候选库读取失败，按空处理：%s", e)
        return pl.DataFrame(schema=_CANDIDATES_SCHEMA)


def save_candidate(c: core.CandidateResult, user_id: str | None = None) -> str:
    """候选入库（status=pending，永不自动发布）。返回 candidate_id。"""
    cid = "cand_" + "_".join(c.combo)[:40]
    ok, reasons = core.evaluate_gate(c)
    df = load_candidates(user_id)
    row = pl.DataFrame({
        "candidate_id": [cid], "combo": [json.dumps(list(c.combo))],
        "directions": [json.dumps(c.directions)], "status": ["pending"],
        "oos_sharpe": [c.oos_sharpe], "oos_max_drawdown": [c.oos_max_drawdown],
        "oos_trades": [c.oos_trades], "valid_folds": [c.valid_folds],
        "positive_fold_ratio": [c.positive_fold_ratio],
        "gate_reasons": [json.dumps(reasons, ensure_ascii=False)],
        "created_at": [date.today().isoformat()], "published_at": [None],
    }, schema={**_CANDIDATES_SCHEMA, "published_at": pl.String})
    out = df.filter(pl.col("candidate_id") != cid)
    out = pl.concat([out, row])
    f = _candidates_file(user_id)
    f.parent.mkdir(parents=True, exist_ok=True)
    out.write_parquet(f)
    logger.info("候选 %s 入库（pending，gate=%s）", cid, "达标" if ok else "未达标")
    return cid


def publish_candidate(candidate_id: str, user_id: str | None = None) -> tuple[bool, str]:
    """发布候选为独立策略（唯一发布入口）。

    铁律：必须过晋级门槛才发布；未达标返回原因。发布动作本身是用户显式触发的
    （本函数由 CLI/API 调用，挖掘流程永不自动调用）。
    """
    df = load_candidates(user_id)
    row = df.filter(pl.col("candidate_id") == candidate_id)
    if row.is_empty():
        return False, f"候选不存在 {candidate_id!r}"
    r = row.row(0, named=True)
    cr = core.CandidateResult(
        combo=tuple(json.loads(r["combo"])), directions=json.loads(r["directions"]),
    )
    # 重建最小 folds 用于门槛判定（直接用库存指标）
    cr.folds = [
        core.FoldResult(
            fold_index=i, combo=cr.combo, oos_sharpe=r["oos_sharpe"],
            oos_return=1.0 if r["positive_fold_ratio"] > 0 else -1.0,
            oos_max_drawdown=r["oos_max_drawdown"], oos_trades=r["oos_trades"],
            oos_positive=r["positive_fold_ratio"] > 0,
        )
        for i in range(r["valid_folds"])
    ]
    ok, reasons = core.evaluate_gate(cr)
    if not ok:
        return False, "未达晋级门槛：" + "；".join(reasons)
    out = df.with_columns(
        pl.when(pl.col("candidate_id") == candidate_id)
        .then(pl.lit("published")).otherwise(pl.col("status")).alias("status"),
        pl.when(pl.col("candidate_id") == candidate_id)
        .then(pl.lit(date.today().isoformat())).otherwise(pl.col("published_at")).alias("published_at"),
    )
    out.write_parquet(_candidates_file(user_id))
    logger.info("候选 %s 已发布", candidate_id)
    return True, "已发布"
