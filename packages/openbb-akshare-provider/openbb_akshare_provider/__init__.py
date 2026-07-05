"""AKShare provider module — A 股深度数据接入 OpenBB Platform."""

from openbb_core.provider.abstract.provider import Provider
from openbb_akshare_provider.models.concept_boards import (
    AKShareConceptBoardsFetcher,
)
from openbb_akshare_provider.models.dragon_tiger_list import (
    AKShareDragonTigerFetcher,
)
from openbb_akshare_provider.models.equity_historical import (
    AKShareEquityHistoricalFetcher,
)
from openbb_akshare_provider.models.index_historical import (
    AKShareIndexHistoricalFetcher,
)
from openbb_akshare_provider.models.margin_trading import (
    AKShareMarginTradingFetcher,
)
from openbb_akshare_provider.models.north_flow import AKShareNorthFlowFetcher
from openbb_akshare_provider.models.stock_quote import AKShareStockQuoteFetcher

akshare_provider = Provider(
    name="akshare",
    website="https://akshare.akfamily.xyz",
    description="""AKShare is an open-source financial data interface library for Python,
offering access to A-share (China stock market) data including real-time quotes,
historical prices, fundamentals, margin trading, dragon tiger list, north flow,
and concept boards. Data sourced from Eastmoney, Sina, and other Chinese providers.""",
    fetcher_dict={
        "EquityQuote": AKShareStockQuoteFetcher,
        "EquityHistorical": AKShareEquityHistoricalFetcher,
        "IndexHistorical": AKShareIndexHistoricalFetcher,
        "NorthFlow": AKShareNorthFlowFetcher,
        "MarginTrading": AKShareMarginTradingFetcher,
        "DragonTigerList": AKShareDragonTigerFetcher,
        "ConceptBoards": AKShareConceptBoardsFetcher,
    },
)
