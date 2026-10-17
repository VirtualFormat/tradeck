"""市场矩阵：从 Parquet 缓存构建「时间 × 标的」列存矩阵。

构建原则（回测正确性命门）：
- 全局交易日轴为所有标的交易日的并集（outer join），停牌/缺行一律 NaN，
  绝不把下一行数据错位接上。
- 价格口径为 daily_prices 原始价（adjust=none）；复权在 engine/adjust.py 做，这里不管。
- 矩阵只在内存构建，不做落盘缓存、多线程、懒加载（保持简单）。
- 字段默认 float32（环境变量 QUANT_MATRIX_DTYPE=float64 可回退）：价格/量
  精度足够（相对误差 ~1e-7，不会翻转信号），内存直接减半——全市场
  universe（5455 只 × 多年日K）的矩阵物化是容器 OOM 的头号来源。
- 两段式入口（内存优化方向 B）：
  prefetch_async（async）：只做回源补拉落盘 + 覆盖率统计，不物化大矩阵，
    供主进程（HTTP API）调用——网络 IO 与 parquet 写留在主进程/worker 池外，
    内存密集的 build() 下沉到 spawn 子进程（OOM 也只杀子进程，事件循环
    不被 numpy 物化阻塞）。
  build_async（async）：prefetch + build 一步到位的包装，仍在用的调用方：
    app/jobs.py 每日信号 job 暖缓存、runner.py 分钟面板暖缓存 /
    run_backtest_async 同进程回测、api_screen 暖缓存（返回值丢弃，仅为补拉）。
  build() 保持纯缓存读（cli / worker 子进程等同步调用方行为不变）。
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np
import polars as pl

from app.config import settings
from app.data import store

logger = logging.getLogger(__name__)

# 矩阵字段（与 store._SCHEMA 的 OHLCV/amount 列一一对应）
FIELDS = ("open", "high", "low", "close", "volume", "amount")


@dataclass
class MarketMatrix:
    """市场矩阵：dates 为全局交易日轴（升序），symbols 为标的轴（升序）。

    每个字段一个 (len(dates), len(symbols)) 的浮点二维数组（默认 float32，
    见 build 的 dtype 参数），缺失为 NaN。
    """

    dates: list[date]
    symbols: list[str]
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray
    amount: np.ndarray

    @property
    def shape(self) -> tuple[int, int]:
        """（交易日数, 标的数）。"""
        return (len(self.dates), len(self.symbols))

    def slice(self, start: date | None = None, end: date | None = None) -> "MarketMatrix":
        """按日期区间切片（闭区间；None 表示该端不限制）。"""
        rows = [
            i
            for i, d in enumerate(self.dates)
            if (start is None or d >= start) and (end is None or d <= end)
        ]
        idx = np.array(rows, dtype=int)
        return MarketMatrix(
            dates=[self.dates[i] for i in rows],
            symbols=self.symbols,
            **{f: getattr(self, f)[idx] for f in FIELDS},
        )

    def select(self, symbols: list[str]) -> "MarketMatrix":
        """按标的子集选列（保持传入顺序；不存在的标的报 KeyError）。"""
        col_of = {s: j for j, s in enumerate(self.symbols)}
        missing = [s for s in symbols if s not in col_of]
        if missing:
            raise KeyError(f"矩阵中不存在的标的：{missing}")
        idx = np.array([col_of[s] for s in symbols], dtype=int)
        return MarketMatrix(
            dates=self.dates,
            symbols=list(symbols),
            **{f: getattr(self, f)[:, idx] for f in FIELDS},
        )


def build(
    symbols: list[str],
    start: date,
    end: date,
    dtype: np.dtype | type | None = None,
) -> MarketMatrix:
    """从 data 层 Parquet 缓存构建市场矩阵。

    逐标的读 store.load，过滤到 [start, end] 后 outer join 到全局交易日轴；
    缓存为空/损坏的标的保留为全 NaN 列（优雅降级，不抛错）。

    dtype：矩阵字段的浮点精度，默认读环境变量 QUANT_MATRIX_DTYPE
    （"float64" 回退旧口径），缺省 float32（内存减半，见模块 docstring）。
    """
    if dtype is None:
        env = os.environ.get("QUANT_MATRIX_DTYPE", "").lower()
        if env == "float64":
            dtype = np.float64
        else:
            # 非法值（手误如 float6）记 warning 后按默认 float32 优雅降级，不抛错
            if env and env != "float32":
                logger.warning(
                    "QUANT_MATRIX_DTYPE=%r 非法（仅支持 float32/float64），按 float32 处理",
                    os.environ.get("QUANT_MATRIX_DTYPE"),
                )
            dtype = np.float32
    syms = sorted(symbols)
    frames: list[pl.DataFrame] = []
    for s in syms:
        df = store.load(s)
        if not df.is_empty():
            # 防御性去重排序（store.save 已保证，重复 date 时后写胜出与 UPSERT 语义一致）
            df = (
                df.filter((pl.col("date") >= start) & (pl.col("date") <= end))
                .unique(subset=["date"], keep="last")
                .sort("date")
            )
        frames.append(df)

    # 全局交易日轴：所有标的交易日的并集，升序
    dates = sorted({d for df in frames for d in df["date"].to_list()})
    row_of = {d: i for i, d in enumerate(dates)}

    n_dates, n_syms = len(dates), len(syms)
    fields = {f: np.full((n_dates, n_syms), np.nan, dtype=dtype) for f in FIELDS}
    for j, df in enumerate(frames):
        if df.is_empty():
            logger.warning("标的 %s 缓存为空，矩阵对应列全为 NaN", syms[j])
            continue
        rows = np.array([row_of[d] for d in df["date"].to_list()], dtype=int)
        for f in FIELDS:
            # 统一转浮点：Int64 的 volume 含 null 时也能安全落进 NaN 矩阵
            fields[f][rows, j] = df[f].cast(pl.Float64).to_numpy().astype(dtype, copy=False)

    return MarketMatrix(dates=dates, symbols=syms, **fields)


def _checked_file(symbol: str) -> Path:
    """停牌水位标记文件路径（与 parquet 缓存同目录的 sidecar）。"""
    return store._file_of(symbol).parent / f"symbol={symbol}.checked.json"


def _read_checked(symbol: str) -> dict | None:
    """读水位标记；不存在或损坏返回 None（按未检查过处理，正常补拉）。"""
    path = _checked_file(symbol)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {
            "last_checked_date": date.fromisoformat(data["last_checked_date"]),
            "requested_start": date.fromisoformat(data["requested_start"]),
            "requested_end": date.fromisoformat(data["requested_end"]),
        }
    except Exception as e:  # 损坏当未检查过：正常补拉并重建标记
        logger.warning("水位标记读取失败，按未检查处理（%s）：%s", path, e)
        return None


def _write_checked(symbol: str, start: date, end: date) -> None:
    """写水位标记：tmp + rename 原子落盘（与缓存写入同风格，防半写文件）。

    语义：last_checked_date 表示「该标的在 [requested_start, last_checked_date]
    内已确认无任何数据」，覆盖判定据此跳过重复补拉。
    """
    path = _checked_file(symbol)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "last_checked_date": end.isoformat(),
        "requested_start": start.isoformat(),
        "requested_end": end.isoformat(),
    }
    # tmp 文件名带 PID：并发 build_async 写同一标的时各写各的临时文件，
    # rename 原子覆盖，不留半写文件（固定名 tmp 会被并发协程互相覆盖）
    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


async def prefetch_async(
    symbols: list[str],
    start: date,
    end: date,
) -> dict:
    """异步预拉：缓存缺失标的回源补拉落盘（只写 parquet，不物化矩阵）。

    覆盖判定：区间内行数为 0 = 全缺；有数据但首尾日期盖不住 [start, end] = 部分缺
    （与 store.missing_ranges 同口径，区间内的停牌空洞不算缺）。
    停牌水位：缓存仍缺但 sidecar 的 last_checked_date >= end，说明此前已确认到
    end 为止无任何数据（长期停牌/退市尾部空洞），跳过补拉直接全 NaN 降级；
    sidecar 的 last_checked_date < end 时正常补拉，补拉后按结果更新/清除标记。
    有缺失标的时，经 client.fetch_bars 一次性批量补拉
    （自带分片分窗），逐标的 store.merge + store.save 落缓存，之后重新走 build()。
    「跳过回源」的语义由同步 build() 承担（纯缓存读），本函数始终按需回源。

    返回覆盖率摘要（供调用方做预拉失败前置判定，替代旧的全矩阵物化检查）：
      {"total", "covered", "coverage", "missing", "stale_checked"}；
      coverage = 区间内有数据的标的占比（基于 parquet 元数据/轻量读，不建矩阵）。

    降级语义（与 build 一致，绝不抛错）：
    - 补拉请求整体失败 / 单个标的没补到数据：该标的计为未覆盖；
    - 只记日志，摘要照常返回。

    注意：补拉只发生在主进程（HTTP API / CLI 的 async 入口）；worker 子进程
    只调同步 build() 读已暖好的缓存，不做网络 IO（与分钟K 预拉模式一致）。
    本函数刻意不物化矩阵（内存优化方向 B）：大 universe 的 numpy 物化下沉到
    spawn 子进程，主进程事件循环不被阻塞、OOM 也只杀子进程。
    """
    from app.data import client

    syms = sorted(symbols)
    if not syms:
        return {"total": 0, "covered": 0, "coverage": 0.0,
                "missing": 0, "stale_checked": 0}

    cached: dict[str, pl.DataFrame] = {}
    missing: list[str] = []
    stale_checked = 0
    for s in syms:
        df = store.load(s)
        if not df.is_empty():
            df = df.filter((pl.col("date") >= start) & (pl.col("date") <= end))
        cached[s] = df
        if (
            df.is_empty()
            or df["date"].min() > start
            or df["date"].max() < end
        ):
            # 水位命中（此前已确认到 end 无数据）则跳过补拉；
            # 缓存有数据的标的顺手清掉过期的历史标记（数据本身即覆盖证明）
            marker = _read_checked(s)
            if marker is not None:
                if df.is_empty() and marker["last_checked_date"] >= end:
                    stale_checked += 1
                    continue
                if not df.is_empty():
                    _checked_file(s).unlink(missing_ok=True)
            missing.append(s)

    if not missing:
        logger.info("prefetch_async：%d 只命中缓存，0 只回源补拉", len(syms))
        return {"total": len(syms), "covered": len(syms), "coverage": 1.0,
                "missing": 0, "stale_checked": 0}

    try:
        bars = await client.fetch_bars(missing, start, end)
    except Exception as e:  # 网络/上游故障不阻塞构建，缺失标的全 NaN 降级
        logger.warning("prefetch_async 补拉失败（%d 只标的按未覆盖计）：%s", len(missing), e)
        covered = len(syms) - len(missing) - stale_checked
        return {
            "total": len(syms), "covered": covered,
            "coverage": covered / len(syms),
            "missing": len(missing), "stale_checked": stale_checked,
        }

    # 按 symbol 分桶后逐标的 merge 落缓存（bars_to_frame 空列表返回空 schema 表）
    by_symbol: dict[str, list[dict]] = {s: [] for s in missing}
    for bar in bars:
        if bar.get("symbol") in by_symbol:
            by_symbol[bar["symbol"]].append(bar)
    filled = 0
    for s in missing:
        if not by_symbol[s]:
            # 补拉仍无数据：落水位标记，下次同区间回测不再重复回源
            _write_checked(s, start, end)
            continue  # 该标的区间内无数据（停牌/退市/上游缺数），保留全 NaN 列
        store.save(s, store.merge(store.load(s), store.bars_to_frame(by_symbol[s])))
        # 补到数据即证明有覆盖，清除可能残留的历史水位标记
        _checked_file(s).unlink(missing_ok=True)
        filled += 1

    failed = len(missing) - filled
    logger.info(
        "prefetch_async：%d 只命中缓存，%d 只水位跳过，%d 只回源补拉（%d 只补拉无数据/失败）",
        len(syms) - len(missing) - stale_checked, stale_checked, len(missing), failed,
    )
    covered = len(syms) - stale_checked - failed
    return {
        "total": len(syms), "covered": covered,
        "coverage": covered / len(syms),
        "missing": len(missing), "stale_checked": stale_checked,
    }


async def build_async(
    symbols: list[str],
    start: date,
    end: date,
    dtype: np.dtype | type | None = None,
) -> MarketMatrix:
    """异步构建市场矩阵：prefetch_async 补拉落缓存 + 同步 build 建矩阵。

    仍在用的调用方：app/jobs.py 每日信号 job 暖缓存、runner.py 分钟面板
    暖缓存 / run_backtest_async 同进程回测（消费返回的矩阵）、api_screen
    暖缓存（返回值丢弃，仅为补拉落盘）。回测/优化系路由已改用
    prefetch_async + worker 子进程内 build()（内存优化方向 B，主进程不再
    物化大矩阵）。
    """
    await prefetch_async(symbols, start, end)
    return build(symbols, start, end, dtype=dtype)
