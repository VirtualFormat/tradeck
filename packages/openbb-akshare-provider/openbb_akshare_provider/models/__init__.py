"""AKShare Provider Models."""

from openbb_akshare_provider.models.concept_boards import (
    AKShareConceptBoardsData,
    AKShareConceptBoardsFetcher,
    AKShareConceptBoardsQueryParams,
)
from openbb_akshare_provider.models.dragon_tiger_list import (
    AKShareDragonTigerData,
    AKShareDragonTigerFetcher,
    AKShareDragonTigerQueryParams,
)
from openbb_akshare_provider.models.equity_historical import (
    AKShareEquityHistoricalData,
    AKShareEquityHistoricalFetcher,
    AKShareEquityHistoricalQueryParams,
)
from openbb_akshare_provider.models.index_historical import (
    AKShareIndexHistoricalData,
    AKShareIndexHistoricalFetcher,
    AKShareIndexHistoricalQueryParams,
)
from openbb_akshare_provider.models.margin_trading import (
    AKShareMarginTradingData,
    AKShareMarginTradingFetcher,
    AKShareMarginTradingQueryParams,
)
from openbb_akshare_provider.models.north_flow import (
    AKShareNorthFlowData,
    AKShareNorthFlowFetcher,
    AKShareNorthFlowQueryParams,
)
from openbb_akshare_provider.models.stock_quote import (
    AKShareStockQuoteData,
    AKShareStockQuoteFetcher,
    AKShareStockQuoteQueryParams,
)

__all__ = [
    "AKShareConceptBoardsData",
    "AKShareConceptBoardsFetcher",
    "AKShareConceptBoardsQueryParams",
    "AKShareDragonTigerData",
    "AKShareDragonTigerFetcher",
    "AKShareDragonTigerQueryParams",
    "AKShareEquityHistoricalData",
    "AKShareEquityHistoricalFetcher",
    "AKShareEquityHistoricalQueryParams",
    "AKShareIndexHistoricalData",
    "AKShareIndexHistoricalFetcher",
    "AKShareIndexHistoricalQueryParams",
    "AKShareMarginTradingData",
    "AKShareMarginTradingFetcher",
    "AKShareMarginTradingQueryParams",
    "AKShareNorthFlowData",
    "AKShareNorthFlowFetcher",
    "AKShareNorthFlowQueryParams",
    "AKShareStockQuoteData",
    "AKShareStockQuoteFetcher",
    "AKShareStockQuoteQueryParams",
]
