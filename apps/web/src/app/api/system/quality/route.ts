/**
 * 数据质量度量 API 代理
 * GET /api/system/quality?days=N（days 默认 7，透传 backend）
 */
import { NextResponse } from "next/server";

const BACKEND_API_URL =
  process.env.BACKEND_API_URL ?? "http://localhost:8080";

export async function GET(request: Request) {
  const days = new URL(request.url).searchParams.get("days") ?? "7";
  try {
    const res = await fetch(
      `${BACKEND_API_URL}/api/system/quality?days=${encodeURIComponent(days)}`,
      {
        headers: { Accept: "application/json" },
        cache: "no-store",
      }
    );
    if (!res.ok) {
      return NextResponse.json(
        { metrics: [], recent_rejects: [] },
        { status: res.status }
      );
    }
    return NextResponse.json(await res.json());
  } catch (err) {
    console.error("system quality proxy failed:", err);
    return NextResponse.json(
      { metrics: [], recent_rejects: [] },
      { status: 502 }
    );
  }
}
