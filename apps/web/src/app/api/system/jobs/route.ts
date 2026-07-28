/**
 * 任务进度 API 路由
 * GET /api/system/jobs
 * 代理 tradeck backend（内存进度注册表）
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
      return NextResponse.json([]);
    }
    const data = await res.json();
    return NextResponse.json(data);
  } catch (err) {
    console.error("system/jobs proxy failed:", err);
    return NextResponse.json([]);
  }
}
