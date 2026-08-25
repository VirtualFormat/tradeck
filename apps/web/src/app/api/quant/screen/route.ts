/**
 * 量化选股 API 路由
 * POST /api/quant/screen
 * 代理 quant 容器（条件筛选），失败降级返回空结果
 */
import { NextRequest, NextResponse } from "next/server";

const QUANT_API_URL = process.env.QUANT_API_URL ?? "http://localhost:8083";

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const res = await fetch(`${QUANT_API_URL}/api/screen`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify(body),
      cache: "no-store",
    });
    if (!res.ok) {
      return NextResponse.json({ rows: [], total: 0 });
    }
    return NextResponse.json(await res.json());
  } catch (err) {
    console.error("quant screen proxy failed:", err);
    return NextResponse.json({ rows: [], total: 0 });
  }
}
