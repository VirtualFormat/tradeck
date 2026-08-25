"""除权因子（TickFlow ex_factors）— 回测动态复权的数据源。

原始价日K（adjust=none）× 因子在引擎内合成前复权序列（见 engine/adjust.py，阶段 B）。
因子缺失的标的降级为「无复权」并显式标注（优雅降级，不静默当已复权）。
免费档 TickFlow.free() 无 ex_factors（付费档），无 key 时全部降级。
"""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import polars as pl

from app.config import settings

logger = logging.getLogger(__name__)

# 因子缓存列定义：除权日 + 因子（TickFlow 返回 timestamp 毫秒 + ex_factor）
_SCHEMA = {"date": pl.Date, "ex_factor": pl.Float64}


def _file_of(symbol: str) -> Path:
    return Path(settings.QUANT_CACHE_DIR) / "factors" / f"symbol={symbol}.parquet"


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


async def fetch(symbols: list[str]) -> dict[str, pl.DataFrame]:
    """批量拉除权因子并落缓存；返回 {symbol: DataFrame}，失败标的缺席（降级）。"""
    if not settings.TICKFLOW_API_KEY:
        logger.warning("未配置 TICKFLOW_API_KEY（免费档无 ex_factors），全部标的按无复权降级")
        return {}
    from tickflow import AsyncTickFlow  # 延迟导入：无 key 场景不加载 SDK

    result: dict[str, pl.DataFrame] = {}
    try:
        async with AsyncTickFlow(api_key=settings.TICKFLOW_API_KEY) as tf:
            raw = await tf.klines.ex_factors(symbols)
    except Exception as e:  # 限流/网络/权限：整批降级，不阻塞行情主链路
        logger.warning("ex_factors 拉取失败，按无复权降级：%s", e)
        return {}
    for symbol, entries in (raw or {}).items():
        if not entries:
            continue
        df = pl.DataFrame(
            {
                "date": [date.fromtimestamp(e["timestamp"] / 1000) for e in entries],
                "ex_factor": [float(e["ex_factor"]) for e in entries],
            }
        ).sort("date")
        path = _file_of(symbol)
        path.parent.mkdir(parents=True, exist_ok=True)
        df.write_parquet(path)
        result[symbol] = df
    missing = set(symbols) - set(result)
    if missing:
        logger.info("ex_factors 缺失 %d 只（无除权记录或拉取失败），按无复权降级：%s",
                    len(missing), sorted(missing)[:5])
    return result
