/**
 * 筛选器 API 路由
 * GET /api/screener?type=gainers|losers|active|undervalued_large_caps|undervalued_growth
 * 代理 OpenBB discovery 端点
 * 加 60 秒内存缓存避免重复调 OpenBB（yfinance discovery 慢，10-30s/次）
 */
import { NextRequest, NextResponse } from "next/server";

const OPENBB_API_URL =
  process.env.OPENBB_API_URL ?? "http://localhost:6900";

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

// 内存缓存（60 秒，discovery 数据不需要实时）
const CACHE_TTL = 60_000;
const cache = new Map<string, { data: ScreenerItem[]; ts: number }>();

export async function GET(request: NextRequest) {
  const type = request.nextUrl.searchParams.get("type") ?? "gainers";

  if (!VALID_TYPES.includes(type)) {
    return NextResponse.json(
      { error: `Invalid type: ${type}` },
      { status: 400 }
    );
  }

  // 检查缓存
  const cached = cache.get(type);
  if (cached && Date.now() - cached.ts < CACHE_TTL) {
    return NextResponse.json(cached.data);
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
    const data = JSON.parse(text);
    const results: ScreenerItem[] = data.results ?? [];

    // 写缓存
    cache.set(type, { data: results, ts: Date.now() });

    return NextResponse.json(results);
  } catch (err) {
    console.error(`Screener ${type} failed:`, err);
    return NextResponse.json([]);
  }
}
