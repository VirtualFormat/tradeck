/**
 * AI 策略生成 API 路由（任务化）
 * POST /api/quant/ai-generate
 * 代理 quant 容器：登记生成任务，立即返回 {task_id}（202）；
 * 未配置 AI 时 quant 返回 200 {valid:false, error}，原样透传给前端降级展示。
 */
import { NextRequest, NextResponse } from "next/server";
import { requireSessionUser } from "@/app/api/_guard";
import { quantFetch } from "@/lib/quant";

export const dynamic = "force-dynamic";

export async function POST(request: NextRequest) {
  const user = await requireSessionUser();
  if (user instanceof NextResponse) return user;
  try {
    const body = await request.json();
    const res = await quantFetch(user, `/api/ai/generate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      cache: "no-store",
    });
    const data = await res.json().catch(() => null);
    if (res.status >= 400 && res.status < 500 && data !== null) {
      // 429 在途任务超限等业务拒绝：透传 detail，前端直接展示
      return NextResponse.json(data, { status: res.status });
    }
    if (!res.ok || data === null) {
      return NextResponse.json(
        { error: "backend unavailable" },
        { status: 502 }
      );
    }
    return NextResponse.json(data, { status: res.status });
  } catch (err) {
    console.error("quant ai-generate proxy failed:", err);
    return NextResponse.json(
      { error: "backend unavailable" },
      { status: 502 }
    );
  }
}
