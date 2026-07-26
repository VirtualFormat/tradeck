"""AKShare Stock Quote Model — A 股实时报价."""

import asyncio
from typing import Any
from warnings import warn

from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.standard_models.equity_quote import (
    EquityQuoteData,
    EquityQuoteQueryParams,
)
from pydantic import Field

# 模块级并发闸：realtime_quotes 一次 ~100 只齐发，无上限 gather 是最高危封 IP 点。
# provider 与 backend 是独立包，无法复用 backend 的 call_akshare，此处本地实现等价语义。
_QUOTE_SEM = asyncio.Semaphore(4)

# 退避重试配置（与 backend datasource.call_akshare 语义一致）
_RETRIES = 2
_BASE_DELAY = 0.5
_BACKOFF = 1.5


class AKShareStockQuoteQueryParams(EquityQuoteQueryParams):
    """AKShare Stock Quote Query."""

    __json_schema_extra__ = {"symbol": {"multiple_items_allowed": True}}


class AKShareStockQuoteData(EquityQuoteData):
    """AKShare Stock Quote Data."""

    # AKShare 返回字段映射到标准模型
    __alias_dict__ = {
        "last_price": "最新价",
        "change": "涨跌额",
        "change_percent": "涨跌幅",
        "volume": "成交量",
        "amount": "成交额",
        "open": "今开",
        "high": "最高",
        "low": "最低",
        "prev_close": "昨收",
        "name": "名称",
    }

    amount: float | None = Field(
        default=None,
        description="Trading amount in CNY.",
    )
    turnover_rate: float | None = Field(
        default=None,
        description="Turnover rate as a percentage.",
    )
    pe_ratio: float | None = Field(
        default=None,
        description="Price-to-earnings ratio.",
    )
    pb_ratio: float | None = Field(
        default=None,
        description="Price-to-book ratio.",
    )
    total_market_cap: float | None = Field(
        default=None,
        description="Total market capitalization in CNY.",
    )
    circ_market_cap: float | None = Field(
        default=None,
        description="Circulating market capitalization in CNY.",
    )


class AKShareStockQuoteFetcher(
    Fetcher[AKShareStockQuoteQueryParams, list[AKShareStockQuoteData]]
):
    """AKShare Stock Quote Fetcher."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> AKShareStockQuoteQueryParams:
        """Transform the query."""
        return AKShareStockQuoteQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: AKShareStockQuoteQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Extract the raw data from AKShare."""
        import akshare as ak

        symbols = [s.strip().upper() for s in query.symbol.split(",") if s.strip()]
        results: list[dict] = []

        async def get_one(sym: str) -> dict | None:
            # 标准化：600519.SH → 600519，000001.SZ → 000001
            code = sym.split(".")[0] if "." in sym else sym

            def fetch_individual() -> dict | None:
                # 优先用 stock_individual_info_em（单股，轻量）
                try:
                    info = ak.stock_individual_info_em(symbol=code)
                    # 返回 DataFrame，转 dict
                    return dict(zip(info["item"], info["value"]))
                except Exception:
                    pass

                # 降级：用 stock_bid_ask_em（实时盘口）
                try:
                    bid_ask = ak.stock_bid_ask_em(symbol=code)
                    return dict(zip(bid_ask["item"], bid_ask["value"]))
                except Exception:
                    pass

                return None

            # 并发闸 + 退避重试（实际并发 ≤ 4）
            async with _QUOTE_SEM:
                data = None
                for attempt in range(_RETRIES + 1):
                    try:
                        data = await asyncio.to_thread(fetch_individual)
                        break
                    except Exception as e:  # noqa: BLE001
                        if attempt < _RETRIES:
                            await asyncio.sleep(_BASE_DELAY * _BACKOFF ** attempt)
                        else:
                            warn(f"AKShare quote failed for {sym}: {e}")
                            return None

            if data:
                # 补充标准字段
                data["symbol"] = sym
                data["currency"] = "CNY"
                data["exchange"] = _detect_exchange(code)
                # 字段名映射（中文 → 标准模型字段）
                if "最新价" in data:
                    data["last_price"] = float(data["最新价"])
                if "股票简称" in data:
                    data["name"] = data["股票简称"]
                return data
            return None

        # 并发拉多个 symbol（实际并发受 _QUOTE_SEM 限制）
        tasks = [get_one(s) for s in symbols]
        for result in await asyncio.gather(*tasks):
            if result:
                results.append(result)

        return results

    @staticmethod
    def transform_data(
        query: AKShareStockQuoteQueryParams,
        data: list[dict],
        **kwargs: Any,
    ) -> list[AKShareStockQuoteData]:
        """Transform the data."""
        return [AKShareStockQuoteData.model_validate(d) for d in data]


def _normalize_symbol(code: str) -> str:
    """6 位代码转 .SH/.SZ 格式."""
    if code.startswith("6"):
        return f"{code}.SH"
    if code.startswith(("0", "3")):
        return f"{code}.SZ"
    if code.startswith(("8", "4")):
        return f"{code}.BJ"
    return code


def _detect_exchange(code: str) -> str:
    """根据代码前缀检测交易所."""
    if code.startswith("6"):
        return "SSE"
    if code.startswith(("0", "3")):
        return "SZSE"
    if code.startswith(("8", "4")):
        return "BSE"
    return "Unknown"
