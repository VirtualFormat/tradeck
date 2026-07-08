/**
 * 筛选器 API 路由
 * GET /api/screener?type=gainers|losers|active
 * 代理 tradeck backend（从 DB 读）
 */
import { NextRequest, NextResponse } from "next/server";

const BACKEND_API_URL =
  process.env.BACKEND_API_URL ?? "http://localhost:8080";

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
      `${BACKEND_API_URL}/api/movers?type=${type}&market=US&limit=20`,
      {
        headers: { Accept: "application/json" },
        cache: "no-store",
      }
    );
    if (!res.ok) {
      return NextResponse.json([]);
    }
    const data = await res.json();
    return NextResponse.json(data);
  } catch (err) {
    console.error(`Screener ${type} failed:`, err);
    return NextResponse.json([]);
  }
}
