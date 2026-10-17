"""universe 解析 — symbols 为空时按 universe 档位展开。

档位：
- "hs300"（默认）：沪深300 成分（data-api /api/index/constituents?index=000300.SH，
  collector 现调同花顺，每次实时取；源不可达/为空时回退 tracked 的 cn 子集）
- "csi500"：中证500 成分（同上，index=000905.SH）
- "tracked"：DEFAULT_SIGNAL_UNIVERSE（100 只，与 jobs.py 同源）
- "cn"：A 股全市场（GET data-api /api/universe?market=CN，instrument_master
  asset='stock' 全量；进程内 TTL 缓存，源不可达/为空时回退 tracked 的 cn 子集）
- "us" / "hk"：暂不支持全市场（现阶段只做 A 股量化），回退 tracked 子集 + warning
- "all"：cn 全市场 + tracked 的美股/港股部分

设计纪律：
- 显式 symbols 优先：请求带了 symbols 就用 symbols，忽略 universe 参数
- universe 与 symbols 互斥校验由 API 层做（本模块只管展开）
"""
from __future__ import annotations

import asyncio
import logging
import time

_CN_SUFFIXES = (".SH", ".SS", ".SZ", ".BJ")
_HK_SUFFIX = ".HK"

# 合法档位 → 说明（unknown 报错时列出供排查）
_UNIVERSE_TIERS = ("hs300", "csi500", "tracked", "cn", "us", "hk", "all")

# 指数档位 → 同花顺指数代码（data-api /api/index/constituents 的 index 参数）
_INDEX_TIERS = {"hs300": "000300.SH", "csi500": "000905.SH"}

# 默认档位：沪深300（300 只大盘蓝筹，矩阵内存可控，避免全市场 OOM）
_DEFAULT_TIER = "hs300"

# /api/universe 清单进程内缓存（标的清单分钟级变化无意义，避免每次回测都打 data-api）
_UNIVERSE_CACHE_TTL_SEC = 600
# 失败负缓存 TTL：源不可达时缓存空结果，TTL 内直接走 fallback，
# 避免每次回测都重打 /api/universe 且各等超时
_UNIVERSE_NEGATIVE_TTL_SEC = 60
# 缓存值第三元素为失败标记（True = 负缓存，TTL 内直接回退不再请求）
_universe_cache: dict[str, tuple[float, list[str], bool]] = {}
# per-market 单飞锁：TTL 过期瞬间的并发请求只放一个去打 data-api（锁内二次检查）
_market_locks: dict[str, asyncio.Lock] = {}

logger = logging.getLogger(__name__)


def _tracked() -> list[str]:
    """延迟导入防循环依赖（app.jobs → app.screener → app.universe）。"""
    from app.jobs import DEFAULT_SIGNAL_UNIVERSE

    return list(DEFAULT_SIGNAL_UNIVERSE)


def _market_of(symbol: str) -> str:
    """按 symbol 后缀判市场（与 data/store._market_of 同款规则）。"""
    if symbol.endswith(_CN_SUFFIXES):
        return "cn"
    if symbol.endswith(_HK_SUFFIX):
        return "hk"
    return "us"


async def _fetch_market_symbols(market: str) -> list[str]:
    """从 data-api 拉全市场标的清单（instrument_master asset='stock'）。"""
    from app.data.client import get_json

    data = await get_json("/api/universe", {"market": market})
    if not isinstance(data, dict):
        return []
    symbols = data.get("symbols")
    if not isinstance(symbols, list):
        return []
    return [str(s) for s in symbols if s]


async def _fetch_index_symbols(index_code: str) -> list[str]:
    """从 data-api 拉指数成分（内部转发 collector 现调同花顺，实时取）。"""
    from app.data.client import get_json

    data = await get_json("/api/index/constituents", {"index": index_code})
    if not isinstance(data, dict):
        return []
    symbols = data.get("symbols")
    if not isinstance(symbols, list):
        return []
    return [str(s) for s in symbols if s]


async def _index_symbols(tier: str) -> list[str]:
    """指数档位（hs300/csi500）：现调同花顺成分，源不可达/为空回退 tracked cn 子集。"""
    index_code = _INDEX_TIERS[tier]
    try:
        symbols = await _fetch_index_symbols(index_code)
    except Exception as e:  # noqa: BLE001 — 调用方约定不抛
        logger.warning("/api/index/constituents?index=%s 请求异常：%s", index_code, e)
        symbols = []
    if symbols:
        return symbols
    fallback = [s for s in _tracked() if _market_of(s) == "cn"]
    logger.warning(
        "universe=%s（%s）成分无数据，回退 tracked 子集（%d 只）",
        tier,
        index_code,
        len(fallback),
    )
    return fallback


async def _market_symbols(market: str) -> list[str]:
    """带 TTL 缓存的全市场清单；源不可达/为空时回退 tracked 的市场子集。

    并发去抖：per-market asyncio.Lock 单飞，锁内二次检查缓存（后到协程直接
    吃先到者写入的结果）。失败负缓存：拉取为空/异常时写短 TTL 空结果，
    TTL 内不再请求，直接走 fallback。
    """
    cached = _universe_cache.get(market)
    if _cache_fresh(cached):
        if cached[2]:  # 负缓存命中：TTL 内直接回退，不再请求
            return _fallback(market)
        return list(cached[1])
    lock = _market_locks.setdefault(market, asyncio.Lock())
    async with lock:
        # 锁内二次检查：可能已被先到协程写入（正/负缓存均可能）
        cached = _universe_cache.get(market)
        if _cache_fresh(cached):
            if cached[2]:
                return _fallback(market)
            return list(cached[1])
        try:
            symbols = await _fetch_market_symbols(market)
        except Exception as e:  # 网络异常同样记负缓存（调用方约定不抛，双保险）
            logger.warning("/api/universe?market=%s 请求异常：%s", market, e)
            symbols = []
        if symbols:
            _universe_cache[market] = (time.monotonic(), symbols, False)
            return list(symbols)
        _universe_cache[market] = (time.monotonic(), [], True)
    return _fallback(market)


def _cache_fresh(
    cached: tuple[float, list[str], bool] | None,
) -> bool:
    """缓存是否在 TTL 内（负缓存用短 TTL，正缓存用长 TTL）。"""
    if not cached:
        return False
    ttl = _UNIVERSE_NEGATIVE_TTL_SEC if cached[2] else _UNIVERSE_CACHE_TTL_SEC
    return time.monotonic() - cached[0] < ttl


def _fallback(market: str) -> list[str]:
    """tracked 的市场子集兜底（universe 源不可达时的降级口径）。"""
    fallback = [s for s in _tracked() if _market_of(s) == market.lower()]
    logger.warning(
        "/api/universe?market=%s 无数据，universe 档位回退 tracked 子集（%d 只）",
        market,
        len(fallback),
    )
    return fallback


async def resolve_universe(
    symbols: list[str] | None, universe: str | None
) -> list[str]:
    """symbols 非空原样返回；否则按 universe 档位展开（默认 hs300 沪深300）。"""
    if symbols:
        return list(symbols)

    tier = (universe or _DEFAULT_TIER).strip().lower()
    if tier in _INDEX_TIERS:
        return await _index_symbols(tier)
    if tier == "tracked":
        return _tracked()
    if tier == "cn":
        return await _market_symbols("CN")
    if tier in ("us", "hk"):
        # 现阶段只做 A 股量化：us/hk 全市场档位未接，回退 tracked 子集
        fallback = [s for s in _tracked() if _market_of(s) == tier]
        logger.warning(
            "universe=%s 全市场清单暂未接入（当前仅 cn），回退 tracked 子集（%d 只）",
            tier,
            len(fallback),
        )
        return fallback
    if tier == "all":
        cn = await _market_symbols("CN")
        rest = [s for s in _tracked() if _market_of(s) != "cn"]
        return cn + rest
    raise ValueError(
        f"未知 universe 档位 {universe!r}，合法值：{', '.join(_UNIVERSE_TIERS)}"
    )
