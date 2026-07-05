"""AKShare Margin Trading Model — 融资融券."""

from datetime import date as dateType
from typing import Any
from warnings import warn

from openbb_core.provider.abstract.data import Data
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.abstract.query_params import QueryParams
from pydantic import Field


class AKShareMarginTradingQueryParams(QueryParams):
    """AKShare Margin Trading Query."""

    start_date: dateType | None = Field(default=None, description="Start date.")
    end_date: dateType | None = Field(default=None, description="End date.")


class AKShareMarginTradingData(Data):
    """AKShare Margin Trading Data."""

    date: dateType | None = Field(default=None, description="Trading date.")
    # 融资余额
    financing_balance: float | None = Field(
        default=None, description="Financing balance (100M CNY)."
    )
    financing_buy: float | None = Field(
        default=None, description="Financing buy amount (100M CNY)."
    )
    # 融券余额
    securities_lending_balance: float | None = Field(
        default=None, description="Securities lending balance (100M CNY)."
    )
    securities_lending_sell: float | None = Field(
        default=None, description="Securities lending sell volume (100M CNY)."
    )


class AKShareMarginTradingFetcher(
    Fetcher[AKShareMarginTradingQueryParams, list[AKShareMarginTradingData]]
):
    """AKShare Margin Trading Fetcher."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> AKShareMarginTradingQueryParams:
        return AKShareMarginTradingQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: AKShareMarginTradingQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        import asyncio

        import akshare as ak

        def fetch_szse() -> list[dict]:
            df = ak.stock_margin_detail_szse(date=query.start_date.strftime("%Y%m%d") if query.start_date else None)
            return df.to_dict(orient="records")

        try:
            records = await asyncio.to_thread(fetch_szse)
        except Exception as e:
            warn(f"AKShare margin trading failed: {e}")
            return []

        return records

    @staticmethod
    def transform_data(
        query: AKShareMarginTradingQueryParams,
        data: list[dict],
        **kwargs: Any,
    ) -> list[AKShareMarginTradingData]:
        return [AKShareMarginTradingData.model_validate(d) for d in data]
