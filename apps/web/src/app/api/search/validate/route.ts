import { NextRequest, NextResponse } from "next/server";

import { serviceAuthHeaders } from "@/lib/service-auth";

// 默认兜底仅供本地开发；生产由环境变量注入 tradb data-api 回环地址。
const BACKEND_API_URL =
  process.env.BACKEND_API_URL ?? "http://localhost:8080";

export async function GET(request: NextRequest) {
  const symbols = request.nextUrl.searchParams.get("symbols") ?? "";
  if (!symbols.trim()) {
    return NextResponse.json([]);
  }

  try {
    const response = await fetch(
      `${BACKEND_API_URL}/api/search/validate?symbols=${encodeURIComponent(symbols)}`,
      {
        headers: { Accept: "application/json", ...serviceAuthHeaders() },
        cache: "no-store",
      }
    );
    if (!response.ok) {
      return NextResponse.json(
        { error: "股票代码校验失败" },
        { status: response.status }
      );
    }
    return NextResponse.json(await response.json());
  } catch (error) {
    console.error("symbol validation proxy failed:", error);
    return NextResponse.json(
      { error: "股票代码校验失败" },
      { status: 503 }
    );
  }
}
