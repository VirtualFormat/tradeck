"""universe 解析 — symbols 为空时按 universe 档位展开。

档位：
- "tracked"（默认）：DEFAULT_SIGNAL_UNIVERSE（100 只，与 jobs.py 同源）
- "cn"：A 股全市场（GET data-api /api/universe?market=CN，instrument_master
  asset='stock' 全量；进程内 TTL 缓存，源不可达/为空时回退 tracked 的 cn 子集）
- "us" / "hk"：暂不支持全市场（现阶段只做 A 股量化），回退 tracked 子集 + warning
- "all"：cn 全市场 + tracked 的美股/港股部分

设计纪律：
- 显式 symbols 优先：请求带了 symbols 就用 symbols，忽略 universe 参数
- universe 与 symbols 互斥校验由 API 层做（本模块只管展开）
"""
from __future__ import annotations

import logging
import time

_CN_SUFFIXES = (".SH", ".SS", ".SZ", ".BJ")
_HK_SUFFIX = ".HK"

# 合法档位 → 说明（unknown 报错时列出供排查）
_UNIVERSE_TIERS = ("tracked", "cn", "us", "hk", "all")

# /api/universe 清单进程内缓存（标的清单分钟级变化无意义，避免每次回测都打 data-api）
_UNIVERSE_CACHE_TTL_SEC = 600
_universe_cache: dict[str, tuple[float, list[str]]] = {}

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


async def _market_symbols(market: str) -> list[str]:
    """带 TTL 缓存的全市场清单；源不可达/为空时回退 tracked 的市场子集。"""
    cached = _universe_cache.get(market)
    if cached and time.monotonic() - cached[0] < _UNIVERSE_CACHE_TTL_SEC:
        return list(cached[1])
    symbols = await _fetch_market_symbols(market)
    if symbols:
        _universe_cache[market] = (time.monotonic(), symbols)
        return list(symbols)
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
    """symbols 非空原样返回；否则按 universe 档位展开（默认 tracked）。"""
    if symbols:
        return list(symbols)

    tier = (universe or "tracked").strip().lower()
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
