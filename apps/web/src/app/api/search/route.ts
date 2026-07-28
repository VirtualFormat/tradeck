/**
 * 标的搜索 API 路由
 * GET /api/search?q=xxx&limit=10
 * 代理 tradeck backend（equity_profiles 名称/代码搜索）
 */
import { NextRequest, NextResponse } from "next/server";

const BACKEND_API_URL =
  process.env.BACKEND_API_URL ?? "http://localhost:8080";

export async function GET(request: NextRequest) {
  const q = request.nextUrl.searchParams.get("q") ?? "";
  const limit = request.nextUrl.searchParams.get("limit") ?? "10";
  if (!q.trim()) {
    return NextResponse.json([]);
  }

  try {
    const res = await fetch(
      `${BACKEND_API_URL}/api/search?q=${encodeURIComponent(q)}&limit=${encodeURIComponent(limit)}`,
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
    console.error("search proxy failed:", err);
    return NextResponse.json([]);
  }
}
