/**
 * 数据任务状态 API 代理
 * GET /api/system/jobs
 */
import { NextResponse } from "next/server";

const BACKEND_API_URL =
  process.env.BACKEND_API_URL ?? "http://localhost:8080";

export async function GET() {
  try {
    const res = await fetch(`${BACKEND_API_URL}/api/system/jobs`, {
      headers: { Accept: "application/json" },
      cache: "no-store",
    });
    if (!res.ok) {
      return NextResponse.json([], { status: res.status });
    }
    return NextResponse.json(await res.json());
  } catch (err) {
    console.error("system jobs proxy failed:", err);
    return NextResponse.json([], { status: 502 });
  }
}
