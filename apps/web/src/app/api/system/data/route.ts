/**
 * 数据系统概览 API 代理
 * GET /api/system/data
 */
import { NextResponse } from "next/server";

const BACKEND_API_URL =
  process.env.BACKEND_API_URL ?? "http://localhost:8080";

export async function GET() {
  try {
    const res = await fetch(`${BACKEND_API_URL}/api/system/data`, {
      headers: { Accept: "application/json" },
      cache: "no-store",
    });
    if (!res.ok) {
      return NextResponse.json(
        { jobs: [], tables: [], daily_markets: [], summary: {} },
        { status: res.status }
      );
    }
    return NextResponse.json(await res.json());
  } catch (err) {
    console.error("system data proxy failed:", err);
    return NextResponse.json(
      { jobs: [], tables: [], daily_markets: [], summary: {} },
      { status: 502 }
    );
  }
}
