"""AKShare Index Historical Model — A 股指数历史."""

from typing import Any
from warnings import warn

from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.standard_models.index_historical import (
    IndexHistoricalData,
    IndexHistoricalQueryParams,
)
from pydantic import Field


class AKShareIndexHistoricalQueryParams(IndexHistoricalQueryParams):
    """AKShare Index Historical Query."""

    __json_schema_extra__ = {"symbol": {"multiple_items_allowed": True}}


class AKShareIndexHistoricalData(IndexHistoricalData):
    """AKShare Index Historical Data."""

    __alias_dict__ = {
        "date": "date",
        "open": "open",
        "high": "high",
        "low": "low",
        "close": "close",
        "volume": "volume",
    }


class AKShareIndexHistoricalFetcher(
    Fetcher[AKShareIndexHistoricalQueryParams, list[AKShareIndexHistoricalData]]
):
    """AKShare Index Historical Fetcher."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> AKShareIndexHistoricalQueryParams:
        return AKShareIndexHistoricalQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: AKShareIndexHistoricalQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        import asyncio

        import akshare as ak

        # symbol 映射：000001.SH → sh000001, 399001.SZ → sz399001
        symbols = [s.strip().upper() for s in query.symbol.split(",") if s.strip()]
        results: list[dict] = []

        def fetch_one(sym: str) -> list[dict]:
            code = sym.split(".")[0] if "." in sym else sym
            # 上交所指数（000开头）用 sh 前缀，深交所指数（399开头）用 sz 前缀
            if sym.endswith(".SH") or sym.endswith(".SS"):
                ak_symbol = f"sh{code}"
            elif sym.endswith(".SZ"):
                ak_symbol = f"sz{code}"
            else:
                ak_symbol = code
            df = ak.stock_zh_index_daily_em(symbol=ak_symbol)
            return df.to_dict(orient="records")

        for sym in symbols:
            try:
                records = await asyncio.to_thread(fetch_one, sym)
                for r in records:
                    r["symbol"] = sym
                results.extend(records)
            except Exception as e:
                warn(f"AKShare index historical failed for {sym}: {e}")

        return results

    @staticmethod
    def transform_data(
        query: AKShareIndexHistoricalQueryParams,
        data: list[dict],
        **kwargs: Any,
    ) -> list[AKShareIndexHistoricalData]:
        return [AKShareIndexHistoricalData.model_validate(d) for d in data]
