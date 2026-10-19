/**
 * AI 策略保存 API 路由
 * POST /api/quant/ai-save
 * 代理 quant 容器（AI 策略落盘到 strategies/ai/），失败透传 4xx 错误或 502
 */
import { NextRequest, NextResponse } from "next/server";
import { requireSessionUser } from "@/app/api/_guard";
import { quantFetch } from "@/lib/quant";

export async function POST(request: NextRequest) {
  const user = await requireSessionUser();
  if (user instanceof NextResponse) return user;
  try {
    const body = await request.json();
    const res = await quantFetch(user, `/api/ai/save`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      cache: "no-store",
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      // 透传 quant 的校验错误（422 安全闸拒绝等），前端原样展示 detail
      return NextResponse.json(data, { status: res.status });
    }
    return NextResponse.json(data);
  } catch (err) {
    console.error("quant ai-save proxy failed:", err);
    return NextResponse.json(
      { error: "backend unavailable" },
      { status: 502 }
    );
  }
}
