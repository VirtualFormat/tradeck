/**
 * AI 策略调整 API 路由（任务化）
 * POST /api/quant/ai-tweak
 * 代理 quant 容器：登记调整任务，立即返回 {task_id}（202）；
 * 未配置 AI 时 quant 返回 200 {valid:false, error}，原样透传给前端降级展示。
 */
import { NextRequest, NextResponse } from "next/server";
import { assertSession } from "@/app/api/_guard";

const QUANT_API_URL = process.env.QUANT_API_URL ?? "http://localhost:8083";

export const dynamic = "force-dynamic";

export async function POST(request: NextRequest) {
  const guard = await assertSession();
  if (guard) return guard;
  try {
    const body = await request.json();
    const res = await fetch(`${QUANT_API_URL}/api/ai/tweak`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      cache: "no-store",
    });
    const data = await res.json().catch(() => null);
    if (!res.ok || data === null) {
      return NextResponse.json(
        { error: "backend unavailable" },
        { status: 502 }
      );
    }
    return NextResponse.json(data, { status: res.status });
  } catch (err) {
    console.error("quant ai-tweak proxy failed:", err);
    return NextResponse.json(
      { error: "backend unavailable" },
      { status: 502 }
    );
  }
}
