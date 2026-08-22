"""按 symbol 后缀判定市场（与 apps/backend/app/markets.py 同一契约的精简副本）"""


# A 股后缀：.SH（沪，新标准）/.SS（沪，yfinance 指数仍用）/.SZ/.BJ
_CN_SUFFIXES = (".SH", ".SS", ".SZ", ".BJ")


def pick_market(symbol: str) -> str:
    sym = symbol.upper()
    if sym.endswith(_CN_SUFFIXES):
        return "CN"
    if sym.endswith(".HK"):
        return "HK"
    return "US"
