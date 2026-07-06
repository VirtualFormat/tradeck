/**
 * 筛选器 API 路由
 * GET /api/screener?type=gainers|losers|active|undervalued_large_caps|undervalued_growth
 * 代理 OpenBB discovery 端点
 * 客户端调用，用 no-store 避免缓存（确保切换类型立即刷新）
 */
import { NextRequest, NextResponse } from "next/server";
import {
  OPENBB_API_URL,
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
    const res = await fetch(
      `${OPENBB_API_URL}/api/v1/equity/discovery/${type}?provider=yfinance`,
      {
        headers: { Accept: "application/json" },
        cache: "no-store",
      }
    );
    if (!res.ok) {
      return NextResponse.json([]);
    }
    const text = await res.text();
    if (!text) return NextResponse.json([]);
    const data: OpenBBResponse<ScreenerItem> = JSON.parse(text);
    return NextResponse.json(data.results ?? []);
  } catch (err) {
    console.error(`Screener ${type} failed:`, err);
    return NextResponse.json([]);
  }
}
