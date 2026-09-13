/**
 * 日 K 线 API 路由
 * GET /api/historical?symbol=AAPL&days=180
 * 或精确开窗：GET /api/historical?symbol=AAPL&start_date=2025-01-01&end_date=2025-06-30
 * （start/end 优先于 days；N 阶段 K 线回放 modal 用精确开窗消除尾部偏差）
 * 代理 tradeck backend（从 PostgreSQL 读）
 */
import { NextRequest, NextResponse } from "next/server";

import { serviceAuthHeaders } from "@/lib/service-auth";

// 默认兜底仅供本地开发；生产由环境变量注入 tradb data-api 回环地址。
const BACKEND_API_URL =
  process.env.BACKEND_API_URL ?? "http://localhost:8080";

export async function GET(request: NextRequest) {
  const symbol = request.nextUrl.searchParams.get("symbol") ?? "";
  const days = Number(request.nextUrl.searchParams.get("days") ?? 180);
  const startParam = request.nextUrl.searchParams.get("start_date") ?? "";
  const endParam = request.nextUrl.searchParams.get("end_date") ?? "";

  if (!symbol) {
    return NextResponse.json([]);
  }

  // 精确开窗优先；否则按 days 从今天向前推
  const end = endParam || null;
  const start = startParam || null;
  const fmt = (d: Date) => d.toISOString().slice(0, 10);
  const fallbackEnd = new Date();
  const fallbackStart = new Date(
    fallbackEnd.getTime() - days * 24 * 60 * 60 * 1000
  );

  try {
    const res = await fetch(
      `${BACKEND_API_URL}/api/historical?symbol=${encodeURIComponent(
        symbol
      )}&start_date=${start ?? fmt(fallbackStart)}&end_date=${end ?? fmt(fallbackEnd)}`,
      {
        headers: { Accept: "application/json", ...serviceAuthHeaders() },
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
