/**
 * AI 策略生成 API 路由（SSE 流式）
 * POST /api/quant/ai-generate
 * 代理 quant 容器（AI 策略生成），流式透传给浏览器，失败返回 502 JSON
 */
import { NextRequest, NextResponse } from "next/server";

const QUANT_API_URL = process.env.QUANT_API_URL ?? "http://localhost:8083";

export const dynamic = "force-dynamic";

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const res = await fetch(`${QUANT_API_URL}/api/ai/generate`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "text/event-stream",
      },
      body: JSON.stringify(body),
      cache: "no-store",
    });
    if (!res.ok || !res.body) {
      return NextResponse.json(
        { error: "backend unavailable" },
        { status: 502 }
      );
    }
    // 流式透传：不 await res.json()，直接把上游 SSE 流转给浏览器
    return new Response(res.body, {
      status: res.status,
      headers: {
        "Content-Type":
          res.headers.get("Content-Type") ?? "text/event-stream",
        "Cache-Control": "no-cache, no-transform",
        "X-Accel-Buffering": "no",
      },
    });
  } catch (err) {
    console.error("quant ai-generate proxy failed:", err);
    return NextResponse.json(
      { error: "backend unavailable" },
      { status: 502 }
    );
  }
}
