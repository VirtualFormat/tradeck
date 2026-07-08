/**
 * 批量报价 API 路由
 * GET /api/quotes?symbols=AAPL,MSFT,NVDA
 * 代理 tradeck backend（从 PostgreSQL 读，<50ms）
 */
import { NextRequest, NextResponse } from "next/server";

const BACKEND_API_URL =
  process.env.BACKEND_API_URL ?? "http://localhost:8080";

export async function GET(request: NextRequest) {
  const symbols = request.nextUrl.searchParams.get("symbols") ?? "";

  if (!symbols) {
    return NextResponse.json([]);
  }

  try {
    const res = await fetch(
      `${BACKEND_API_URL}/api/quotes?symbols=${encodeURIComponent(symbols)}`,
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
    console.error(`Quotes failed:`, err);
    return NextResponse.json([]);
  }
}
