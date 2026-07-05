"""AKShare Concept Boards Model — 板块/概念."""

from typing import Any
from warnings import warn

from openbb_core.provider.abstract.data import Data
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.abstract.query_params import QueryParams
from pydantic import Field


class AKShareConceptBoardsQueryParams(QueryParams):
    """AKShare Concept Boards Query."""

    board_type: str = Field(
        default="concept",
        description="Board type: 'concept' or 'industry'.",
    )


class AKShareConceptBoardsData(Data):
    """AKShare Concept Boards Data."""

    name: str | None = Field(default=None, description="Board name.")
    code: str | None = Field(default=None, description="Board code.")
    change_percent: float | None = Field(
        default=None, description="Daily change percent."
    )
    turnover: float | None = Field(
        default=None, description="Turnover amount (100M CNY)."
    )
    leader_stock: str | None = Field(default=None, description="Leader stock name.")
    leader_change: float | None = Field(
        default=None, description="Leader stock change percent."
    )


class AKShareConceptBoardsFetcher(
    Fetcher[AKShareConceptBoardsQueryParams, list[AKShareConceptBoardsData]]
):
    """AKShare Concept Boards Fetcher."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> AKShareConceptBoardsQueryParams:
        return AKShareConceptBoardsQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: AKShareConceptBoardsQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        import asyncio

        import akshare as ak

        def fetch() -> list[dict]:
            if query.board_type == "industry":
                df = ak.stock_board_industry_name_em()
            else:
                df = ak.stock_board_concept_name_em()
            return df.to_dict(orient="records")

        try:
            records = await asyncio.to_thread(fetch)
        except Exception as e:
            warn(f"AKShare concept boards failed: {e}")
            return []

        return records

    @staticmethod
    def transform_data(
        query: AKShareConceptBoardsQueryParams,
        data: list[dict],
        **kwargs: Any,
    ) -> list[AKShareConceptBoardsData]:
        return [AKShareConceptBoardsData.model_validate(d) for d in data]
