"""因子挖掘运行时 — 把核心算法串成完整流程 + 候选库持久化（发布纪律是铁律）。

流程（对齐参照 mining.md 闭环，V1 边界内）：
1. 全样本因子 IC 与方向（仅展示）；带 Newey-West HAC t 值 + p 值 + BH-FDR q 值校正。
2. 真嵌套折：每个外层折的内层折（outer train 内滚动，purge/embargo 隔离）里
   去重、beam 搜索、按内层测试段 IC 选定组合；外层测试段独立评估选定的组合。
3. 候选组合的样本外夏普带 DSR 通缩校正（多重试验后的夏普显著性）。
4. 候选入候选库——显式确认且过门槛才发布，永不自动上线。

防泄漏红线（I1）：折的切分按交易日下标；purge_bars >= horizon 保证训练段尾部
样本的 forward return 窗口不跨入测试段；embargo_bars 保证下一折训练段不回看
本折测试段。

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
from app.mining import stats
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
    # 统计检验（I2）：因子 IC 的 NW t / p 值与 BH-FDR q 值；各候选的 DSR 通缩夏普
    factor_ic_stats: dict[str, dict] | None = None
    candidate_dsr: dict[str, float | None] | None = None
    n_trials: int = 0  # DSR 的 N：内层候选评估总次数（有效折数 × beam_width × max_size，不去重）
    dsr_note: str = ""  # DSR 的 N 口径说明（前端展示用）


def _slice(arr: np.ndarray, start: int, end: int) -> np.ndarray:
    return arr[start:end]


def _backtest_top_n(
    factor_score: np.ndarray, open_: np.ndarray, top_n: int = 5
) -> tuple[float, float, float, int, np.ndarray]:
    """极简多头回测：每日按 T 日因子分选 top_n 只（等权），T+1 开盘买入、
    T+2 开盘卖出（持有 1 个交易日），返回 (夏普, 总收益, 最大回撤, 交易数, 日收益序列)。

    成交口径与主回测引擎（engine/matcher.py 默认 entry_fill/exit_fill="open_t+1"）
    对齐：信号在 T 日收盘后产生，次日开盘成交——挖掘晋级门槛
    （GATE_MIN_OOS_SHARPE 直接用本函数输出）与发布策略的主回测不再系统性偏移。
    保持轻量：不跑完整撮合，只改价格取值点；open 与 close 同口径（复权矩阵）。
    边界：T+1/T+2 超出数据范围或开盘价缺失时跳过该信号日。
    交易数 = 调仓次数（每日换手持仓数变化）。日收益序列用于 DSR 的矩与观测数。
    """
    n_days, n_syms = factor_score.shape
    daily_port: list[float] = []
    trades = 0
    prev_holdings: set[int] = set()
    for t in range(n_days):
        if t + 2 >= n_days:  # T+1/T+2 无开盘数据 → 信号无法成交/了结，跳过
            break
        row = factor_score[t]
        valid = ~np.isnan(row)
        if valid.sum() < top_n:
            continue
        top_idx = np.argsort(np.where(valid, row, -np.inf))[-top_n:]
        holdings = set(int(i) for i in top_idx)
        trades += len(holdings.symmetric_difference(prev_holdings))
        prev_holdings = holdings
        idx = list(holdings)
        entry = open_[t + 1, idx]
        exit_ = open_[t + 2, idx]
        tradable = ~(np.isnan(entry) | np.isnan(exit_))
        if not tradable.any():
            continue
        day_ret = float(np.mean(exit_[tradable] / entry[tradable] - 1.0))
        daily_port.append(day_ret)
    eq = np.array(daily_port)
    if len(eq) < 5:
        return np.nan, 0.0, 0.0, trades, eq
    sharpe = float(eq.mean() / eq.std() * np.sqrt(252)) if eq.std() > 0 else 0.0
    total = float((1 + eq).prod() - 1)
    curve = np.cumprod(1 + eq)
    max_dd = float((curve / np.maximum.accumulate(curve) - 1).min())
    return sharpe, total, max_dd, trades, eq


def _skew_kurt(returns: np.ndarray) -> tuple[float | None, float | None]:
    """日收益序列的偏度与超额前峰度（DSR 用）；样本不足/零方差返回 (None, None)。"""
    n = len(returns)
    if n < 5:
        return None, None
    mu = returns.mean()
    sd = returns.std()
    if sd <= 0:
        return None, None
    z = (returns - mu) / sd
    skew = float(np.mean(z ** 3))
    kurt = float(np.mean(z ** 4))  # 峰度（正态 = 3）
    return skew, kurt


def _select_combo_inner(
    nested: core.NestedFold,
    factors: dict[str, np.ndarray],
    fwd: np.ndarray,
    max_size: int,
    beam_width: int,
) -> (
    tuple[tuple[str, ...], dict[str, int], list[str], list[tuple[str, str]], int] | None
):
    """内层调参：在外层折的各内层折（outer train 内滚动，purge/embargo 隔离）里
    去重 + beam 搜索，按内层测试段 |IC| 均值选定最优组合及其方向。

    返回 (组合, 方向, 去重后保留因子, 去重剔除记录, 本折搜索试验数)；
    选不定（因子不足/无有效组合）返回 None，调用方跳过该外层折。
    """
    # 防御：单折调参无法形成有效的样本外比较（make_nested_folds 已按 <2 跳过，
    # 这里再兜一层，防止调用方绕过折生成直接构造 NestedFold）
    if len(nested.inner) < 2:
        return None
    # 内层训练段因子 IC 与方向（第一个内层折定方向与去重，候选池共享以控成本）
    first = nested.inner[0]
    train_ics, train_dirs = {}, {}
    for name, f in factors.items():
        ics = core.factor_daily_ics(
            f[first.train_start:first.train_end],
            fwd[first.train_start:first.train_end],
        )
        if len(ics) >= 5:
            train_ics[name] = float(np.mean(ics))
            train_dirs[name] = 1 if np.mean(ics) >= 0 else -1
    if not train_ics:
        return None
    train_factors = {
        n: factors[n][first.train_start:first.train_end] for n in train_ics
    }
    corr = core.factor_correlation(train_factors)
    kept, dropped = core.prune_correlated(train_ics, corr, threshold=0.7)
    if not kept:
        return None
    combos = core.beam_search(
        {n: train_factors[n] for n in kept},
        fwd[first.train_start:first.train_end],
        {n: train_ics[n] for n in kept}, train_dirs,
        max_size=max_size, beam_width=beam_width, correlation=corr,
    )
    if not combos:
        return None
    # 内层评估预算：只在 top 候选上比内层测试段 IC（控成本）
    pool = combos[:8]
    # DSR 试验计数：beam 搜索每层扩展 beam_width 条路径、共 max_size 层
    n_evaluations = beam_width * max_size
    best_combo: tuple[str, ...] | None = None
    best_score = -np.inf
    for combo, _ in pool:
        scores = []
        for fold in nested.inner:
            test_score = core.combine_factors(
                {n: factors[n][fold.test_start:fold.test_end] for n in combo},
                combo, {n: train_dirs[n] for n in combo},
            )
            ics = core.factor_daily_ics(
                test_score, fwd[fold.test_start:fold.test_end]
            )
            if ics:
                scores.append(abs(float(np.mean(ics))))
        if scores:
            mean_score = float(np.mean(scores))
            if mean_score > best_score:
                best_score = mean_score
                best_combo = combo
    if best_combo is None:
        return None
    return best_combo, {n: train_dirs[n] for n in best_combo}, kept, dropped, n_evaluations


def _auto_validation_config(
    n_days: int, horizon: int, n_outer: int = 3
) -> core.NestedValidationConfig:
    """按可用交易日数自适应嵌套折窗口（purge 恒 >= horizon，防泄漏不可让步）。

    数据够长（>=默认窗）用参照默认（504/126/63 + 252/63/63）；不足时按比例收缩
    各窗口，保证仍满足：外层 train+purge+test <= n_days、外层训练段容纳 >=1 个内层折。
    """
    purge = max(30, horizon)
    default = core.NestedValidationConfig(purge_bars=purge, embargo_bars=5)
    if core.make_nested_folds(n_days, default):
        return default
    outer_test = max(20, n_days // 8)
    step_room = max(0, n_days - (n_days // 2) - purge - outer_test)
    outer_step = max(20, step_room // max(n_outer - 1, 1)) if n_outer > 1 else 20
    outer_train = max(60, n_days - purge - outer_test - (n_outer - 1) * outer_step)
    inner_train = max(30, outer_train // 2)
    inner_test = max(10, outer_test // 2)
    # 外层训练段须容纳一个内层折：inner_train + purge + inner_test <= outer_train
    while inner_train + purge + inner_test > outer_train and inner_train > 30:
        inner_train = max(30, inner_train - 10)
    return core.NestedValidationConfig(
        outer_train_bars=outer_train, outer_test_bars=outer_test,
        outer_step_bars=outer_step, inner_train_bars=inner_train,
        inner_test_bars=inner_test, inner_step_bars=inner_test,
        purge_bars=purge, embargo_bars=5,
        min_train_bars=min(126, inner_train, outer_train),
    )


def run_mining(
    enriched: EnrichedMatrix,
    horizon: int = 5,
    max_size: int = 4,
    beam_width: int = 16,
    n_outer: int = 3,
    top_n: int = 5,
    user_id: str | None = None,
) -> MiningRunResult:
    """对一批标的跑完整因子挖掘，返回候选（含真嵌套样本外评估 + 统计检验）。

    enriched：复权后的市场矩阵（含指标）。horizon：预测未来 N 日收益。
    user_id：多用户命名空间（K6）——传入时挖掘目录含该用户的 active 因子，
    缺省 None 仅内置 14 因子。
    """
    close = enriched.base.close
    open_ = enriched.base.open
    n_days = close.shape[0]
    factors = factor_catalog(enriched, user_id=user_id)
    fwd = core.forward_returns(close, horizon)

    # 1. 全样本因子 IC（方向由符号定）——仅用于展示，嵌套折内会重算；
    #    带 NW HAC t 值（lag=horizon，吸收前瞻收益自相关）与 BH-FDR q 值（多重检验校正）
    full_ics = {}
    full_daily_ics: dict[str, list[float]] = {}
    for name, f in factors.items():
        ics = core.factor_daily_ics(f, fwd)
        if len(ics) >= 5:
            full_ics[name] = float(np.mean(ics))
            full_daily_ics[name] = ics
    factor_ic_stats: dict[str, dict] = {}
    pvalues: list[float | None] = []
    stat_names: list[str] = []
    for name, ics in full_daily_ics.items():
        t_nw, p_nw, t_naive = stats.daily_ic_stats(ics, lag=horizon)
        factor_ic_stats[name] = {"t_nw": t_nw, "p_nw": p_nw, "t_naive": t_naive}
        stat_names.append(name)
        pvalues.append(p_nw)
    for name, q in zip(stat_names, stats.bh_fdr_qvalues(pvalues)):
        factor_ic_stats[name]["q_bh"] = q

    # 2. 真嵌套折：内层（outer train 内滚动，purge/embargo 隔离）调参选定组合，
    #    外层测试段独立评估——训练/测试的 forward return 窗口被隔离带截断，不跨边界
    config = _auto_validation_config(n_days, horizon, n_outer=n_outer)
    folds = core.make_nested_folds(n_days, config)
    if not folds:
        logger.warning(
            "天数 %d 不足以切嵌套折（purge=%d 不可让步），返回空候选", n_days, config.purge_bars,
        )
        return MiningRunResult(
            0, [], [], full_ics, [], 0,
            factor_ic_stats=factor_ic_stats, candidate_dsr={}, n_trials=0,
            dsr_note="",
        )

    # 3. 每个外层折：内层调参选定组合 → 外层测试段独立评估
    by_combo: dict[tuple[str, ...], core.CandidateResult] = {}
    kept_counts: dict[str, int] = {}
    dropped_counts: dict[tuple[str, str], int] = {}
    n_trials = 0
    for k, nested in enumerate(folds):
        selected = _select_combo_inner(nested, factors, fwd, max_size, beam_width)
        if selected is None:
            logger.warning("外层折 %d 内层调参无有效组合，跳过", k)
            continue
        combo, dirs, kept_k, dropped_k, n_evals = selected
        n_trials += n_evals
        for n in kept_k:
            kept_counts[n] = kept_counts.get(n, 0) + 1
        for pair in dropped_k:
            dropped_counts[pair] = dropped_counts.get(pair, 0) + 1
        outer = nested.outer
        test_score = core.combine_factors(
            {n: factors[n][outer.test_start:outer.test_end] for n in combo},
            combo, dirs,
        )
        test_open = _slice(open_, outer.test_start, outer.test_end)
        sharpe, total, max_dd, trades, daily = _backtest_top_n(
            test_score, test_open, top_n
        )
        if np.isnan(sharpe):
            continue
        skew, kurt = _skew_kurt(daily)
        cr = by_combo.get(combo)
        if cr is None:
            cr = core.CandidateResult(combo=combo, directions=dirs)
            by_combo[combo] = cr
        cr.folds.append(core.FoldResult(
            fold_index=k, combo=combo, oos_sharpe=sharpe, oos_return=total,
            oos_max_drawdown=max_dd, oos_trades=trades, oos_positive=total > 0,
            n_obs=len(daily), oos_skewness=skew, oos_kurtosis=kurt,
        ))
    results = sorted(
        by_combo.values(),
        key=lambda c: -(c.oos_sharpe if not np.isnan(c.oos_sharpe) else -np.inf),
    )
    # 报告口径：取各折去重结果按出镜次数排序（各折内层独立去重）
    kept = sorted(kept_counts, key=lambda n: (-kept_counts[n], n))
    dropped = sorted(dropped_counts, key=lambda p: (-dropped_counts[p], p))

    # 4. DSR 通缩夏普：候选样本外夏普对多重试验校正
    # N 口径：真实搜索空间——各折内层 beam 池的候选评估总次数
    # （折数 × beam_width × max_size，不去重：DSR 惩罚的是搜索强度，
    # 重复评估同一候选也算一次试验）。原口径 max(去重候选数, 1) 系统性低估 N，
    # 导致 expected_max_sharpe 偏低、DSR 偏高，已修正。
    n_trials = max(n_trials, 1)
    dsr_note = (
        f"DSR 的 N 为真实搜索空间估算：折数 × beam_width × max_size "
        f"（本次 N={n_trials}，不去重——DSR 惩罚的是搜索强度）；"
        f"样本外回测为 open_t+1 口径（T 日信号、T+1 开盘买入、T+2 开盘卖出），"
        f"与主回测引擎一致。"
    )
    sharpes = [
        c.oos_sharpe / np.sqrt(252)  # 日化夏普（DSR 矩口径与收益频率一致）
        for c in results if not np.isnan(c.oos_sharpe)
    ]
    # P1-1 修复：var_sr 与 n_trials 口径对齐。n_trials 是不去重的搜索强度
    #（折数 × beam × max_size），var_sr 若只取外层去重候选的方差，当全部折收敛到
    # 同一组合时 len(sharpes)==1 → var_sr=0 → expected_max_sharpe=0，DSR 退化成
    # 裸 PSR（多重试验校正完全失效）——恰是最该惩罚的场景。
    # 修法：var_sr==0 且 n_trials>1 时用保守下界（单候选夏普绝对值的 1% 作为
    # 最小方差，保证 expected_max_sharpe > 0，DSR 仍有惩罚力）。
    var_sr = float(np.var(sharpes, ddof=1)) if len(sharpes) >= 2 else 0.0
    if var_sr == 0.0 and n_trials > 1 and sharpes:
        # 保守下界：用单候选日化夏普绝对值的 1% 作为方差下界
        # （夏普典型量级 0.01~0.1/日，1% 方差 ≈ std 为夏普值的 10%，是合理保守假设）
        var_sr = max(abs(sharpes[0]) * 0.01, 1e-8)
    candidate_dsr: dict[str, float | None] = {}
    for c in results:
        if np.isnan(c.oos_sharpe) or not c.folds:
            candidate_dsr["+".join(c.combo)] = None
            continue
        n_obs = sum(f.n_obs for f in c.folds)
        sr_daily = c.oos_sharpe / np.sqrt(252)
        skew_vals = [f.oos_skewness for f in c.folds if f.oos_skewness is not None]
        kurt_vals = [f.oos_kurtosis for f in c.folds if f.oos_kurtosis is not None]
        candidate_dsr["+".join(c.combo)] = stats.deflated_sharpe_psr(
            sr_daily, n_obs,
            skewness=float(np.mean(skew_vals)) if skew_vals else None,
            kurtosis=float(np.mean(kurt_vals)) if kurt_vals else None,
            n_trials=n_trials, variance_sharpes=var_sr,
        )

    return MiningRunResult(
        n_factors=len(factors), kept_factors=kept, dropped=dropped,
        factor_ics=full_ics, candidates=results, n_folds=len(folds),
        factor_ic_stats=factor_ic_stats, candidate_dsr=candidate_dsr,
        n_trials=n_trials, dsr_note=dsr_note,
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
