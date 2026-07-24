/**
 * 日 K 线 API 路由
 * GET /api/historical?symbol=AAPL&days=180
 * 代理 tradeck backend（从 PostgreSQL 读）
 */
import { NextRequest, NextResponse } from "next/server";

const BACKEND_API_URL =
  process.env.BACKEND_API_URL ?? "http://localhost:8080";

export async function GET(request: NextRequest) {
  const symbol = request.nextUrl.searchParams.get("symbol") ?? "";
  const days = Number(request.nextUrl.searchParams.get("days") ?? 180);

  if (!symbol) {
    return NextResponse.json([]);
  }

  const end = new Date();
  const start = new Date(end.getTime() - days * 24 * 60 * 60 * 1000);
  const fmt = (d: Date) => d.toISOString().slice(0, 10);

  try {
    const res = await fetch(
      `${BACKEND_API_URL}/api/historical?symbol=${encodeURIComponent(
        symbol
      )}&start_date=${fmt(start)}&end_date=${fmt(end)}`,
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
    console.error(`Historical failed:`, err);
    return NextResponse.json([]);
  }
}
