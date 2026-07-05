"""AKShare North Flow Model — 北向资金（沪深港通）."""

from datetime import date as dateType
from typing import Any
from warnings import warn

from openbb_core.provider.abstract.data import Data
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.abstract.query_params import QueryParams
from pydantic import Field


class AKShareNorthFlowQueryParams(QueryParams):
    """AKShare North Flow Query."""

    start_date: dateType | None = Field(
        default=None,
        description="Start date of the data (YYYY-MM-DD).",
    )
    end_date: dateType | None = Field(
        default=None,
        description="End date of the data (YYYY-MM-DD).",
    )


class AKShareNorthFlowData(Data):
    """AKShare North Flow Data."""

    date: dateType | None = Field(default=None, description="Trading date.")
    # 沪股通/深股通净流入
    sh_connect_net_inflow: float | None = Field(
        default=None, description="Shanghai-HK Connect net inflow (100M CNY)."
    )
    sz_connect_net_inflow: float | None = Field(
        default=None, description="Shenzhen-HK Connect net inflow (100M CNY)."
    )
    total_net_inflow: float | None = Field(
        default=None, description="Total north net inflow (100M CNY)."
    )


class AKShareNorthFlowFetcher(
    Fetcher[AKShareNorthFlowQueryParams, list[AKShareNorthFlowData]]
):
    """AKShare North Flow Fetcher."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> AKShareNorthFlowQueryParams:
        return AKShareNorthFlowQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: AKShareNorthFlowQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        import asyncio

        import akshare as ak

        def fetch() -> list[dict]:
            df = ak.stock_hsgt_north_net_flow_in_em(symbol="北向资金")
            return df.to_dict(orient="records")

        try:
            records = await asyncio.to_thread(fetch)
        except Exception as e:
            warn(f"AKShare north flow failed: {e}")
            return []

        # 按日期过滤
        if query.start_date:
            records = [r for r in records if str(r.get("日期", "")) >= query.start_date.strftime("%Y-%m-%d")]
        if query.end_date:
            records = [r for r in records if str(r.get("日期", "")) <= query.end_date.strftime("%Y-%m-%d")]

        return records

    @staticmethod
    def transform_data(
        query: AKShareNorthFlowQueryParams,
        data: list[dict],
        **kwargs: Any,
    ) -> list[AKShareNorthFlowData]:
        return [AKShareNorthFlowData.model_validate(d) for d in data]
