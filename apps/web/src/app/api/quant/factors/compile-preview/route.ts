/**
 * 因子编译预览 API 路由
 * POST /api/quant/factors/compile-preview
 * 代理 quant 容器（DSL 编译诊断 + 样例数据预览），失败返回 502
 */
import { NextRequest, NextResponse } from "next/server";

const QUANT_API_URL = process.env.QUANT_API_URL ?? "http://localhost:8083";

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const res = await fetch(`${QUANT_API_URL}/api/factors/compile-preview`, {
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
    return NextResponse.json(await res.json());
  } catch (err) {
    console.error("quant factors compile-preview proxy failed:", err);
    return NextResponse.json(
      { error: "backend unavailable" },
      { status: 502 }
    );
  }
}
