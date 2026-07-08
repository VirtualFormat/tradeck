"""按市场选 provider（复用前端逻辑）"""


def pick_provider(symbol: str) -> str:
    sym = symbol.upper()
    if sym.endswith(".SS") or sym.endswith(".SZ") or sym.endswith(".BJ"):
        return "akshare"
    return "yfinance"


def pick_market(symbol: str) -> str:
    sym = symbol.upper()
    if sym.endswith(".SS") or sym.endswith(".SZ") or sym.endswith(".BJ"):
        return "CN"
    if sym.endswith(".HK"):
        return "HK"
    return "US"
