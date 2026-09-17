/**
 * AI 生成任务轮询 API 路由
 * GET /api/quant/ai-task/[id] → { status, result?, error? }
 * 代理 quant 容器，失败返回 502（前端轮询层负责重试）
 */
import { NextRequest, NextResponse } from "next/server";
import { assertSession } from "@/app/api/_guard";

const QUANT_API_URL = process.env.QUANT_API_URL ?? "http://localhost:8083";

type Ctx = { params: Promise<{ id: string }> };

export async function GET(_request: NextRequest, ctx: Ctx) {
  const guard = await assertSession();
  if (guard) return guard;
  const { id } = await ctx.params;
  try {
    const res = await fetch(`${QUANT_API_URL}/api/ai/task/${id}`, {
      headers: { Accept: "application/json" },
      cache: "no-store",
    });
    if (!res.ok) {
      return NextResponse.json(
        { error: "backend unavailable" },
        { status: 502 }
      );
    }
    return NextResponse.json(await res.json());
  } catch (err) {
    console.error("quant ai task proxy failed:", err);
    return NextResponse.json(
      { error: "backend unavailable" },
      { status: 502 }
    );
  }
}
