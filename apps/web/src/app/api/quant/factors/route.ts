/**
 * 因子列表 / 创建 API 路由
 * GET/POST /api/quant/factors
 * 代理 quant 容器（因子注册表），失败降级返回空数组 / 502
 */
import { NextRequest, NextResponse } from "next/server";

const QUANT_API_URL = process.env.QUANT_API_URL ?? "http://localhost:8083";

export async function GET() {
  try {
    const res = await fetch(`${QUANT_API_URL}/api/factors`, {
      headers: { Accept: "application/json" },
      cache: "no-store",
    });
    if (!res.ok) {
      return NextResponse.json([]);
    }
    return NextResponse.json(await res.json());
  } catch (err) {
    console.error("quant factors proxy failed:", err);
    return NextResponse.json([]);
  }
}

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const res = await fetch(`${QUANT_API_URL}/api/factors`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify(body),
      cache: "no-store",
    });
    if (!res.ok) {
      const data = (await res.json().catch(() => null)) as {
        detail?: string;
      } | null;
      return NextResponse.json(
        { error: data?.detail ?? "backend unavailable" },
        { status: res.status }
      );
    }
    return NextResponse.json(await res.json(), { status: res.status });
  } catch (err) {
    console.error("quant factors proxy failed:", err);
    return NextResponse.json(
      { error: "backend unavailable" },
      { status: 502 }
    );
  }
}
