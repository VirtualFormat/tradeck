"""分钟频策略回放 — 逐交易日回放分钟流，产出盘中入场命中（含触发时刻）。

与阶段 H1 的区别：H1 是日K 信号的成交价修正（matcher 内部用分钟K 优化成交价），
H2 让策略**直接消费分钟流**——每日以「截至 T-1 的完成态日K 窗口 + 当日分钟序列」
构造策略输入，跑出盘中入场命中。

回放定位（H2）：产出盘中**入场命中**（含触发时刻），只做入场侧回放，
出场/撮合/绩效统计不在本模块——命中列表供 H3 出场回放或报告消费。

语义铁律（对齐参照 tick-stock-panel backend/app/backtest/minute_replay.py）：
- 防未来函数：日线窗口严格截至 T-1（不含当日），当日只用分钟流；
- 策略输入构造：当日分钟流由策略的 compute 经其自有通道读取
  （分钟频策略约定从 params["_minute_bars_today"] 取当日帧，键为回放器注入的
  私有键，普通日频策略不可见/不受影响），回放器只负责按日切换注入内容；
- 触发时刻：分钟策略可在返回的 StrategySignals 上附加 minute_triggers 属性
  （{symbol: 触发分钟 datetime}，动态属性协议），命中价/时刻取该分钟收盘；
  未提供时降级当日最后一根分钟K（时刻语义为「当日信号确认」）；
- 按交易日精确对日：无分钟分区的日子显式跳过，不做「回退最近分区」；
- 涨停拒买：触发分钟收盘已达当日涨停价（limit_pct + T-1 原始收盘）则拒买；
- 复权折算：命中价按当日复权因子比例折算到复权价系（与 adjust.py 前复权
  同口径），因子缓存缺失降级原始价（≈ 因子 1.0）并记入 unadjusted。
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np
import polars as pl

from app.engine.adjust import _factor_series
from app.engine.limits import limit_pct
from app.matrix import MarketMatrix, enrich
from app.strategy.loader import StrategyDef

logger = logging.getLogger(__name__)

__all__ = ["MinuteReplayHit", "MinuteReplayResult", "replay_minute_strategy",
           "MINUTE_BARS_PARAM_KEY"]

# 回放器注入 params 的当日分钟流私有键（分钟频策略 compute 内读取当日分钟帧；
# 下划线前缀与普通策略参数隔离，日频策略永不可见）
MINUTE_BARS_PARAM_KEY = "_minute_bars_today"

# 日K 帧字段（与 matrix/market.FIELDS 一致；回放面板直接用原始价日K 缓存帧）
_DAILY_FIELDS = ("open", "high", "low", "close", "volume", "amount")


@dataclass
class MinuteReplayHit:
    """一个盘中入场命中：触发分钟收盘买入（entry_price 已折算到复权价系）。"""
    trade_date: date
    symbol: str
    entry_price: float
    trigger_time: str  # 触发分钟K 的时间戳 "HH:MM"
    score: float = 0.0


@dataclass
class MinuteReplayResult:
    replayed_days: int = 0
    skipped_days: list[date] = field(default_factory=list)  # 无分钟分区 / 单日执行失败日
    hits: list[MinuteReplayHit] = field(default_factory=list)
    buy_limit_up: int = 0  # 触发分钟收盘已达涨停价而拒买的次数
    unadjusted: list[str] = field(default_factory=list)  # 复权因子缺失、按原始价折算的标的
    elapsed_ms: float = 0.0


def _trigger_hhmm(value) -> str:
    """从分钟K datetime 提取 "HH:MM"（naive datetime 按本地时间原样取）。"""
    if hasattr(value, "strftime"):
        return value.strftime("%H:%M")
    text = str(value or "")
    return text[11:16] if len(text) >= 16 else ""


def _daily_window_matrix(
    frames: dict[str, pl.DataFrame],
    symbols: list[str],
    end_date: date,
    window: int,
) -> MarketMatrix:
    """截取截至 end_date（含）的最近 window 根完成态日K，构造 MarketMatrix。

    数据来自预加载的 frames（不再过 store，回放器本身零 IO）；
    交易日轴为窗口内各标的交易日的并集，缺失为 NaN（与 matrix.build 同语义）。
    """
    dates = sorted({d for df in frames.values() for d in df["date"].to_list() if d <= end_date})
    if window > 0:
        dates = dates[-window:]
    row_of = {d: i for i, d in enumerate(dates)}
    n_dates, n_syms = len(dates), len(symbols)
    fields = {f: np.full((n_dates, n_syms), np.nan) for f in _DAILY_FIELDS}
    for j, df in enumerate(frames.values()):
        part = df.filter(pl.col("date").is_in(dates))
        if part.is_empty():
            continue
        rows = np.array([row_of[d] for d in part["date"].to_list()], dtype=int)
        for f in _DAILY_FIELDS:
            fields[f][rows, j] = part[f].cast(pl.Float64).to_numpy()
    return MarketMatrix(dates=dates, symbols=list(symbols), **fields)


def _placeholder_matrix(symbols: list[str], day: date) -> MarketMatrix:
    """无日线窗口（纯分钟策略 / 面板起点之前的分区日）的占位矩阵。

    一根全 NaN 行保持矩阵形状（1 日 × N 标的），策略的日线指标自然全 NaN，
    分钟条件不受影响。date 取 T 前一日仅作形状载体，不含任何行情数据。
    """
    return MarketMatrix(
        dates=[day - timedelta(days=1)], symbols=list(symbols),
        **{f: np.full((1, len(symbols)), np.nan) for f in _DAILY_FIELDS},
    )


def _adj_factor_of(
    symbol: str, day: date, factors: dict[str, pl.DataFrame] | None
) -> float:
    """当日复权折算比例 = 前复权口径 factor[day] / factor[T_last]（与 adjust.py 同口径）。

    分钟价为未复权真实价，乘以该比例折算到复权价系，与日线出场价同尺度
    （参照实现用面板 close/raw_close 比例，此处日K 缓存全为原始价、无 raw_close 列，
    用因子比例同义实现）。因子缺失 → 1.0（降级原始价）。
    """
    if not factors:
        return 1.0
    fac = factors.get(symbol)
    if fac is None or fac.is_empty():
        return 1.0
    series = _factor_series(fac, [day])
    last_f = fac["ex_factor"].to_numpy()[-1]
    if last_f == 0:
        return 1.0
    return float(series[0] / last_f)


def replay_minute_strategy(
    strategy: StrategyDef,
    *,
    daily: dict[str, pl.DataFrame],
    minute: dict[str, pl.DataFrame],
    start: date,
    end: date,
    params: dict | None = None,
    factors: dict[str, pl.DataFrame] | None = None,
    progress_cb: Callable[[dict], None] | None = None,
    cancel_event=None,
) -> MinuteReplayResult:
    """逐交易日回放分钟策略，产出盘中入场命中。

    daily：{symbol: 日K DataFrame}（原始价，调用方应覆盖 [start - 窗口预热, end]）；
    minute：{symbol: 分钟K DataFrame}（datetime/open/high/low/close/volume/amount）；
    factors：{symbol: 复权因子缓存帧}（缺省/缺失标的降级原始价折算）。
    progress_cb 每回放日回调 {"day": i, "total": n, "date": "YYYY-MM-DD"}；
    cancel_event.is_set() 时提前终止（已产出的命中保留）。
    """
    t0 = time.perf_counter()
    result = MinuteReplayResult()

    # 合并参数默认值（与 registry.run 同语义）
    merged = {**{p["id"]: p.get("default") for p in strategy.params_schema}, **(params or {})}
    window = strategy.minute_daily_bars

    # 日线面板帧（预加载，回放器零 IO）
    frames: dict[str, pl.DataFrame] = {}
    all_daily_dates: set[date] = set()
    for sym, df in daily.items():
        if df is None or df.is_empty():
            continue
        frames[sym] = df
        all_daily_dates.update(df["date"].to_list())
    daily_dates = sorted(all_daily_dates)
    if not frames or not daily_dates:
        logger.warning("分钟回放 %s：日线面板为空，直接返回空结果", strategy.strategy_id)
        result.elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
        return result
    symbols = sorted(frames)

    # 分钟流按 (自然日, symbol) 预分组（回放主循环零额外切片成本）；
    # 无分钟分区的交易日显式记 skipped，不做「回退最近分区」（对齐参照语义）
    minute_by_day: dict[date, dict[str, pl.DataFrame]] = {}
    end_next = end + timedelta(days=1)
    for sym, df in minute.items():
        if df is None or df.is_empty():
            continue
        part = df.filter(
            (pl.col("datetime") >= pl.lit(start).cast(pl.Datetime))
            & (pl.col("datetime") < pl.lit(end_next).cast(pl.Datetime))
        )
        if part.is_empty():
            continue
        for key, sub in part.group_by(part["datetime"].dt.date(), maintain_order=True):
            minute_by_day.setdefault(key[0], {})[sym] = sub

    replay_days = [d for d in daily_dates if start <= d <= end]
    minute_day_set = set(minute_by_day)
    result.skipped_days = [d for d in replay_days if d not in minute_day_set]
    days = [d for d in replay_days if d in minute_day_set]
    total = len(days)

    def day_minutes_of(day: date) -> dict[str, pl.DataFrame]:
        """当日分钟流（私有注入键的值）：{symbol: 当日分钟帧}，无分区标的缺席。"""
        return minute_by_day.get(day, {})

    unadjusted: set[str] = set()
    for i, day in enumerate(days):
        if cancel_event is not None and cancel_event.is_set():
            break
        if progress_cb is not None:
            progress_cb({"day": i + 1, "total": max(total, 1), "date": str(day)})

        # 日线窗口：严格截至 T-1 的完成态日K（不含当日，防未来函数）
        has_prior = any(d < day for d in daily_dates)
        if has_prior and window > 0:
            last_prior = max(d for d in daily_dates if d < day)
            win_matrix = _daily_window_matrix(frames, symbols, last_prior, window)
        else:
            win_matrix = _placeholder_matrix(symbols, day)

        enriched = enrich(win_matrix)
        try:
            # 注入当日分钟流（私有键）：分钟频策略 compute 内
            # params["_minute_bars_today"] 读取 {symbol: 当日分钟帧}；
            # 普通日频策略不收该键、行为完全不变。
            day_params = {**merged, MINUTE_BARS_PARAM_KEY: day_minutes_of(day)}
            sig = strategy.compute_fn(enriched, day_params)
        except Exception as e:  # 单日策略异常记跳过，不中断整个回放（对齐参照单日容错）
            logger.warning("分钟回放 %s %s 策略执行异常，该日记跳过：%s",
                           strategy.strategy_id, day, e)
            result.skipped_days.append(day)
            continue

        result.replayed_days += 1
        # 信号取窗口最后一行（T-1 行）——策略的日线条件只读到 T-1；
        # 分钟条件的因果性由策略自身保证（回放器只喂当日分钟流）
        last = len(win_matrix.dates) - 1
        day_minutes = minute_by_day[day]
        # 策略上报的精确触发分钟（动态属性协议；缺省 None → 降级当日最后一根）
        triggers = getattr(sig, "minute_triggers", None) or {}
        for j, sym in enumerate(win_matrix.symbols):
            try:
                fired = bool(sig.entry[last, j])
            except Exception:
                continue
            if not fired:
                continue
            mdf = day_minutes.get(sym)
            if mdf is None or mdf.is_empty():
                continue
            # 触发分钟：优先策略上报的 minute_triggers，降级当日最后一根
            trigger = triggers.get(sym)
            row = mdf.filter(pl.col("datetime") == trigger) if trigger is not None else pl.DataFrame()
            if row.is_empty():
                trigger = mdf["datetime"][-1]
                raw_close = float(mdf["close"][-1])
            else:
                trigger = row["datetime"][0]
                raw_close = float(row["close"][0])
            if not np.isfinite(raw_close) or raw_close <= 0:
                continue
            # 涨停拒买：触发分钟收盘已达当日涨停价（limit_pct + T-1 原始收盘）
            prev_row = frames[sym].filter(pl.col("date") < day).tail(1)
            if not prev_row.is_empty():
                prev_close = float(prev_row["close"][0])
                if prev_close > 0:
                    limit_up = prev_close * (1 + limit_pct(sym, day, ""))
                    if raw_close >= limit_up - 1e-9:
                        result.buy_limit_up += 1
                        continue
            adj = _adj_factor_of(sym, day, factors)
            if factors is not None and adj == 1.0 and (
                factors.get(sym) is None or factors.get(sym).is_empty()
            ):
                unadjusted.add(sym)
            try:
                score = float(sig.score[last, j])
            except Exception:
                score = 0.0
            result.hits.append(MinuteReplayHit(
                trade_date=day,
                symbol=sym,
                entry_price=raw_close * adj,
                trigger_time=_trigger_hhmm(trigger),
                score=score if np.isfinite(score) else 0.0,
            ))

    result.unadjusted = sorted(unadjusted)
    result.elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
    return result
