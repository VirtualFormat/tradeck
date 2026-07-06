/**
 * 批量报价 API 路由
 * GET /api/quotes?symbols=AAPL,MSFT,NVDA
 * 代理 OpenBB equity/price/quote（支持多 symbol）
 */
import { NextRequest, NextResponse } from "next/server";
import {
  fetchJSON,
  type OpenBBResponse,
  type EquityQuote,
} from "@/lib/openbb";

interface QuoteItem {
  symbol: string;
  name: string | null;
  last_price: number | null;
  change: number | null;
  change_percent: number | null;
  volume: number | null;
  exchange: string | null;
}

export async function GET(request: NextRequest) {
  const symbols = request.nextUrl.searchParams.get("symbols") ?? "";

  if (!symbols) {
    return NextResponse.json([]);
  }

  try {
    const data = await fetchJSON<OpenBBResponse<EquityQuote>>(
      `/equity/price/quote?provider=yfinance&symbol=${encodeURIComponent(symbols)}`
    );
    const results: QuoteItem[] = (data.results ?? []).map((r) => ({
      symbol: r.symbol,
      name: r.name,
      last_price: r.last_price,
      change: r.change,
      change_percent: r.change_percent,
      volume: r.volume,
      exchange: r.exchange,
    }));
    return NextResponse.json(results);
  } catch (err) {
    console.error(`Quotes failed:`, err);
    return NextResponse.json([]);
  }
}
