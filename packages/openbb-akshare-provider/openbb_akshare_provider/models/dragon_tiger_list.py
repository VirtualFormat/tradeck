"""AKShare Dragon Tiger List Model — 龙虎榜."""

from datetime import date as dateType
from typing import Any
from warnings import warn

from openbb_core.provider.abstract.data import Data
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.abstract.query_params import QueryParams
from pydantic import Field


class AKShareDragonTigerQueryParams(QueryParams):
    """AKShare Dragon Tiger List Query."""

    start_date: dateType | None = Field(default=None, description="Start date.")
    end_date: dateType | None = Field(default=None, description="End date.")


class AKShareDragonTigerData(Data):
    """AKShare Dragon Tiger List Data."""

    code: str | None = Field(default=None, description="Stock code.")
    name: str | None = Field(default=None, description="Stock name.")
    date: dateType | None = Field(default=None, description="Trading date.")
    close: float | None = Field(default=None, description="Close price.")
    change_percent: float | None = Field(default=None, description="Change percent.")
    net_buy: float | None = Field(default=None, description="Net buy amount (CNY).")
    buy_amount: float | None = Field(default=None, description="Buy amount (CNY).")
    sell_amount: float | None = Field(default=None, description="Sell amount (CNY).")
    reason: str | None = Field(default=None, description="Reason for listing.")


class AKShareDragonTigerFetcher(
    Fetcher[AKShareDragonTigerQueryParams, list[AKShareDragonTigerData]]
):
    """AKShare Dragon Tiger List Fetcher."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> AKShareDragonTigerQueryParams:
        return AKShareDragonTigerQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: AKShareDragonTigerQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        import asyncio

        import akshare as ak

        # 默认拉最近一个月
        end = query.end_date or date.today()
        start = query.start_date or date(end.year, max(1, end.month - 1), end.day)

        def fetch() -> list[dict]:
            df = ak.stock_lhb_detail_em(
                start_date=start.strftime("%Y%m%d"),
                end_date=end.strftime("%Y%m%d"),
            )
            return df.to_dict(orient="records")

        try:
            records = await asyncio.to_thread(fetch)
        except Exception as e:
            warn(f"AKShare dragon tiger list failed: {e}")
            return []

        return records

    @staticmethod
    def transform_data(
        query: AKShareDragonTigerQueryParams,
        data: list[dict],
        **kwargs: Any,
    ) -> list[AKShareDragonTigerData]:
        return [AKShareDragonTigerData.model_validate(d) for d in data]
