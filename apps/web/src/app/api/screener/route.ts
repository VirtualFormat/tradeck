/**
 * 筛选器 API 路由
 * GET /api/screener?type=gainers|losers|active|undervalued_large_caps|undervalued_growth
 * 代理 OpenBB discovery 端点
 */
import { NextRequest, NextResponse } from "next/server";
import {
  OPENBB_API_URL,
  fetchJSON,
  type OpenBBResponse,
} from "@/lib/openbb";

interface ScreenerItem {
  symbol: string;
  name: string | null;
  price: number | null;
  change: number | null;
  change_percent: number | null;
  volume: number | null;
  exchange: string | null;
}

const VALID_TYPES = [
  "gainers",
  "losers",
  "active",
  "undervalued_large_caps",
  "undervalued_growth",
  "growth_tech",
  "aggressive_small_caps",
];

export async function GET(request: NextRequest) {
  const type = request.nextUrl.searchParams.get("type") ?? "gainers";

  if (!VALID_TYPES.includes(type)) {
    return NextResponse.json(
      { error: `Invalid type: ${type}` },
      { status: 400 }
    );
  }

  try {
    const data = await fetchJSON<OpenBBResponse<ScreenerItem>>(
      `/equity/discovery/${type}?provider=yfinance`
    );
    return NextResponse.json(data.results ?? []);
  } catch (err) {
    console.error(`Screener ${type} failed:`, err);
    return NextResponse.json([]);
  }
}
