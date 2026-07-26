"""AKShare provider module — A 股实时报价接入 OpenBB Platform.

日K/指数已迁 TickFlow，深度数据（板块/资金流/研报/公告/龙虎/两融/北向）
由 backend 经统一数据层门面直调 akshare。本 provider 仅保留 A 股报价
（realtime_quotes 依赖 /equity/price/quote?provider=akshare）。
"""

from openbb_core.provider.abstract.provider import Provider
from openbb_akshare_provider.models.stock_quote import AKShareStockQuoteFetcher

akshare_provider = Provider(
    name="akshare",
    website="https://akshare.akfamily.xyz",
    description="""AKShare is an open-source financial data interface library for Python,
offering access to A-share (China stock market) real-time quotes.
Data sourced from Eastmoney, Sina, and other Chinese providers.""",
    fetcher_dict={
        "EquityQuote": AKShareStockQuoteFetcher,
    },
)
