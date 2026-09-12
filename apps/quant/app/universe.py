"""universe 解析 — symbols 为空时按 universe 档位展开。

档位：
- "tracked"（默认）：DEFAULT_SIGNAL_UNIVERSE（100 只，与 jobs.py 同源）
- "cn" / "us" / "hk"：分市场全量（从 data-api /api/bars 的 symbol 清单拉；
  当前阶段 data-api 无清单端点，先用 tracked 的市场子集占位，留 TODO 接全市场）
- "all"：tracked 的全集（= "tracked"，占位同上）

设计纪律：
- 显式 symbols 优先：请求带了 symbols 就用 symbols，忽略 universe 参数
- universe 与 symbols 互斥校验由 API 层做（本模块只管展开）
"""
from __future__ import annotations

_CN_SUFFIXES = (".SH", ".SS", ".SZ", ".BJ")
_HK_SUFFIX = ".HK"

# 合法档位 → 说明（unknown 报错时列出供排查）
_UNIVERSE_TIERS = ("tracked", "cn", "us", "hk", "all")


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


def resolve_universe(symbols: list[str] | None, universe: str | None) -> list[str]:
    """symbols 非空原样返回；否则按 universe 档位展开（默认 tracked）。"""
    if symbols:
        return list(symbols)

    tier = (universe or "tracked").strip().lower()
    if tier in ("tracked", "all"):
        # TODO: "all" 后续接 data-api 全市场 symbol 清单（当前占位 = tracked 全集）
        return _tracked()
    if tier in ("cn", "us", "hk"):
        # TODO: 分市场档位后续接 data-api 全市场清单按市场过滤（当前占位 = tracked 子集）
        return [s for s in _tracked() if _market_of(s) == tier]
    raise ValueError(
        f"未知 universe 档位 {universe!r}，合法值：{', '.join(_UNIVERSE_TIERS)}"
    )
