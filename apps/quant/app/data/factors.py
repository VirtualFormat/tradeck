"""复权因子（data-api /api/factors → adjust_factors 表）— 回测动态复权的数据源。

原始价日K（adjust=none）× 因子在引擎内合成前复权序列（见 engine/adjust.py，阶段 B）。
qfq 为日频前复权因子（最新交易日 = 1.0，历史向最新价看齐，见
apps/data-collector/app/jobs/adjust_factors.py），与 ex_factor 缓存列语义兼容：
_factor_series 把因子对齐交易日轴后 factor[T_last]=1，engine 再除一次 1.0 为恒等。
因子缺失的标的降级为「无复权」并显式标注（优雅降级，不静默当已复权）。
注意：adjust_factors 表当前只有 A 股（CN）；US/HK 标的查询自然缺席 → 走降级
（unadjusted 标注），为预期行为，待因子源扩展到港美股后自动覆盖。
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date, timedelta
from pathlib import Path

import polars as pl

from app.config import settings
from app.data import client

logger = logging.getLogger(__name__)

# 因子缓存列定义：date + ex_factor（落盘布局与下游 engine/adjust.py 的契约，不可改）
_SCHEMA = {"date": pl.Date, "ex_factor": pl.Float64}

# 无日期窗时的默认查询起点：A 股最早标的 1990 年上市，1980 足够兜底全历史
_DEFAULT_START = date(1980, 1, 1)


def _file_of(symbol: str) -> Path:
    return Path(settings.QUANT_CACHE_DIR) / "factors" / f"symbol={symbol}.parquet"


def _meta_of(symbol: str) -> Path:
    """因子缓存的元数据 sidecar 路径（与 parquet 同目录，记录新鲜度信息）。"""
    return Path(settings.QUANT_CACHE_DIR) / "factors" / f"symbol={symbol}.meta.json"


def _write_meta(symbol: str, df: pl.DataFrame) -> None:
    """写缓存 meta sidecar：fetched_at（落盘当日）+ 因子最大日期 + 行数。

    qfq 锚定「最新交易日」，标的除权后服务端因子全表重建、历史 qfq 整体平移；
    meta 是缓存新鲜度的唯一判据，is_stale 据此决定是否需要重拉。
    meta 写失败只记日志（缺 meta 会被判 stale 触发重拉，不影响本次结果）。
    """
    meta = {
        "symbol": symbol,
        "fetched_at": date.today().isoformat(),
        "max_date": df["date"].max().isoformat() if not df.is_empty() else None,
        "rows": df.height,
    }
    # 原子写：同目录 tmp + os.replace，防崩溃留半截 JSON（半截 meta 会被
    # is_stale 判 stale 无限重拉，虽然可自愈但徒增回源）
    meta_path = _meta_of(symbol)
    tmp = meta_path.with_name(f"{meta_path.name}.tmp.{os.getpid()}")
    try:
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, meta_path)
    except OSError as e:
        tmp.unlink(missing_ok=True)  # 失败不留残文件
        logger.warning("因子缓存 meta 写入失败（%s 将按 stale 重拉）：%s", symbol, e)


def is_stale(symbol: str, max_age_days: int = 1) -> bool:
    """判定因子缓存是否过期（需要重拉）。

    以下任一成立即 stale：
    - 缓存 parquet 与 meta 都不存在（从未拉过）；
    - meta sidecar 缺失或损坏（旧缓存兼容：一律视为 stale，触发一次重拉）；
    - meta.fetched_at 距今天超过 max_age_days 天。
    meta 存在且新鲜但 parquet 缺席 = 近期已确认「无因子记录」，不算 stale
    （避免无因子标的每次回测重复回源不收敛）。
    只读 meta 小文件，不读 parquet 全表。
    """
    meta_path = _meta_of(symbol)
    if not meta_path.exists():
        return True
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        fetched_at = date.fromisoformat(meta["fetched_at"])
    except (OSError, ValueError, KeyError, TypeError) as e:
        logger.warning("因子缓存 meta 损坏，按 stale 处理（%s）：%s", meta_path, e)
        return True
    return (date.today() - fetched_at).days > max_age_days


def load(symbol: str) -> pl.DataFrame:
    """读单标的因子缓存；不存在或损坏返回空表（= 无因子，调用方走降级）。"""
    path = _file_of(symbol)
    if not path.exists():
        return pl.DataFrame(schema=_SCHEMA)
    try:
        return pl.read_parquet(path)
    except Exception as e:
        logger.warning("因子缓存读取失败，按无因子处理（%s）：%s", path, e)
        return pl.DataFrame(schema=_SCHEMA)


async def fetch(
    symbols: list[str],
    start: date | None = None,
    end: date | None = None,
) -> dict[str, pl.DataFrame]:
    """批量拉复权因子并落缓存；返回 {symbol: DataFrame}，缺失标的缺席（降级）。

    start/end 默认 None = 全历史（拉因子通常要覆盖回测全区间）。
    data-api 返回缺某标的（无因子记录、或当前仅覆盖 A 股时的 US/HK 标的）→
    该标的缺席结果 + logger.info 标注，调用方按无复权处理。
    """
    rows = await client.fetch_factors(
        symbols,
        start or _DEFAULT_START,
        end or (date.today() + timedelta(days=1)),  # +1 天兜住含当日的未来除权预告
    )
    if not rows:
        logger.warning("/api/factors 返回空（%d 只标的均无因子或服务降级），按无复权降级", len(symbols))
        return {}

    by_symbol: dict[str, list[dict]] = {}
    for r in rows:
        if r.get("qfq") is None or r.get("date") is None:
            continue
        by_symbol.setdefault(r["symbol"], []).append(r)

    result: dict[str, pl.DataFrame] = {}
    for symbol, entries in by_symbol.items():
        df = pl.DataFrame(
            {
                "date": [date.fromisoformat(e["date"]) for e in entries],
                "ex_factor": [float(e["qfq"]) for e in entries],
            }
        ).sort("date")
        path = _file_of(symbol)
        path.parent.mkdir(parents=True, exist_ok=True)
        # 原子写：同目录 tmp + os.replace（与 data/store.save 同款语义），
        # 防崩溃留半截 parquet / 并发写互相覆盖
        tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}")
        try:
            df.write_parquet(tmp)
            os.replace(tmp, path)
        except BaseException:
            tmp.unlink(missing_ok=True)  # 失败不留残文件
            raise
        _write_meta(symbol, df)
        result[symbol] = df
    missing = set(symbols) - set(result)
    if missing:
        logger.info("复权因子缺失 %d 只（无因子记录或非 CN 市场），按无复权降级：%s",
                    len(missing), sorted(missing)[:5])
        # 无因子标的也落 meta（rows=0）：meta 新鲜即不判 stale（见 is_stale 判据），
        # 否则同一批无因子标的每次回测都重复回源不收敛。
        for symbol in missing:
            _write_meta(symbol, pl.DataFrame(schema=_SCHEMA))
    return result
