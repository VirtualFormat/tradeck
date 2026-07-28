"""按市场选 provider（复用前端逻辑）"""


# A 股后缀：.SH（沪，新标准）/.SS（沪，yfinance 指数仍用）/.SZ/.BJ
_CN_SUFFIXES = (".SH", ".SS", ".SZ", ".BJ")


def pick_provider(symbol: str) -> str:
    sym = symbol.upper()
    if sym.endswith(_CN_SUFFIXES):
        return "akshare"
    return "yfinance"


def pick_market(symbol: str) -> str:
    sym = symbol.upper()
    if sym.endswith(_CN_SUFFIXES):
        return "CN"
    if sym.endswith(".HK"):
        return "HK"
    return "US"


def to_yahoo_symbol(symbol: str) -> str:
    """tradeck 规范 symbol → Yahoo/yfinance 格式（出向映射，调 yfinance 前用）。

    - 沪市个股 .SH → .SS（Yahoo/Reuters 用 .SS；指数 000001.SS 本就是 .SS，不受影响）
    - 港股 5 位补零 → 4 位（00700.HK → 0700.HK；Yahoo 港股不补零到 5 位）
    - 其余（.SZ/.BJ/美股裸码/指数/商品期货）两阵营一致，原样返回

    响应里的 symbol 是 Yahoo 格式，调用方写库前需自行映射回规范格式。
    """
    sym = symbol.strip().upper()
    if sym.endswith(".SH"):
        return sym[:-3] + ".SS"
    if sym.endswith(".HK"):
        code, _, suffix = sym.partition(".")
        return f"{code.lstrip('0').zfill(4)}.{suffix}"
    return sym
