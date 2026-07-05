"""AKShare Equity Historical Model — A 股历史 K 线."""

from datetime import datetime
from typing import Any
from warnings import warn

from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.standard_models.equity_historical import (
    EquityHistoricalData,
    EquityHistoricalQueryParams,
)
from pydantic import Field


class AKShareEquityHistoricalQueryParams(EquityHistoricalQueryParams):
    """AKShare Equity Historical Query."""

    interval: str = Field(
        default="1d",
        description="Data granularity: 1d, 1wk, 1mo.",
    )


class AKShareEquityHistoricalData(EquityHistoricalData):
    """AKShare Equity Historical Data."""

    __alias_dict__ = {
        "date": "日期",
        "open": "开盘",
        "high": "最高",
        "low": "最低",
        "close": "收盘",
        "volume": "成交量",
        "amount": "成交额",
    }

    amount: float | None = Field(
        default=None,
        description="Trading amount in CNY.",
    )
    turnover_rate: float | None = Field(
        default=None,
        description="Turnover rate as a percentage.",
    )


class AKShareEquityHistoricalFetcher(
    Fetcher[AKShareEquityHistoricalQueryParams, list[AKShareEquityHistoricalData]]
):
    """AKShare Equity Historical Fetcher."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> AKShareEquityHistoricalQueryParams:
        """Transform the query."""
        return AKShareEquityHistoricalQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: AKShareEquityHistoricalQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Extract the raw data from AKShare."""
        import asyncio

        import akshare as ak

        # 标准化 symbol：600519.SH → 600519
        symbol = query.symbol.split(".")[0] if "." in query.symbol else query.symbol

        # 日期格式
        start = query.start_date.strftime("%Y%m%d") if query.start_date else "20200101"
        end = query.end_date.strftime("%Y%m%d") if query.end_date else datetime.now().strftime("%Y%m%d")

        # 周期映射
        period_map = {"1d": "daily", "1wk": "weekly", "1mo": "monthly"}
        ak_period = period_map.get(query.interval, "daily")

        def fetch() -> list[dict]:
            df = ak.stock_zh_a_hist(
                symbol=symbol,
                period=ak_period,
                start_date=start,
                end_date=end,
                adjust="qfq",  # 前复权
            )
            return df.to_dict(orient="records")

        try:
            records = await asyncio.to_thread(fetch)
        except Exception as e:
            warn(f"AKShare stock_zh_a_hist failed for {symbol}: {e}")
            return []

        return records

    @staticmethod
    def transform_data(
        query: AKShareEquityHistoricalQueryParams,
        data: list[dict],
        **kwargs: Any,
    ) -> list[AKShareEquityHistoricalData]:
        """Transform the data."""
        return [AKShareEquityHistoricalData.model_validate(d) for d in data]
