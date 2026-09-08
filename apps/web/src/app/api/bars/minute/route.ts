/**
 * 分钟 K 线 API 路由
 * GET /api/bars/minute?symbols=AAPL,600519.SH&start_date=2026-08-01&end_date=2026-08-02&limit=100000
 * 代理 tradeck backend（data-api 从 ClickHouse 温层读，不可达时上游已降级为空数组）
 */
import { NextRequest, NextResponse } from "next/server";

import { serviceAuthHeaders } from "@/lib/service-auth";

// 默认兜底仅供本地开发；生产由环境变量注入 tradb data-api 回环地址。
const BACKEND_API_URL =
  process.env.BACKEND_API_URL ?? "http://localhost:8080";

export async function GET(request: NextRequest) {
  // 原样透传 query（symbols/start_date/end_date/limit 由 data-api 校验，非法返回 422）
  const query = request.nextUrl.search;

  if (!request.nextUrl.searchParams.get("symbols")) {
    return NextResponse.json([]);
  }

  try {
    const res = await fetch(`${BACKEND_API_URL}/api/bars/minute${query}`, {
      headers: { Accept: "application/json", ...serviceAuthHeaders() },
      cache: "no-store",
    });
    if (!res.ok) {
      return NextResponse.json([]);
    }
    const data = await res.json();
    // 透传截断标记，供消费方判断是否需缩小时间窗
    const truncated = res.headers.get("X-Truncated");
    return NextResponse.json(data, {
      headers: truncated ? { "X-Truncated": truncated } : undefined,
    });
  } catch (err) {
    console.error(`Minute bars failed:`, err);
    return NextResponse.json([]);
  }
}
