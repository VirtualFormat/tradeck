/**
 * 取消 AI 进行中的 agent loop
 * POST /api/ai/sessions/[id]/cancel
 */
import { NextResponse } from "next/server";
import { vibeTradingFetch } from "@/lib/vibe-trading";

type Ctx = { params: Promise<{ id: string }> };

export async function POST(_request: Request, ctx: Ctx) {
  const { id } = await ctx.params;
  try {
    const res = await vibeTradingFetch(`/sessions/${id}/cancel`, { method: "POST" });
    const data = await res.json().catch(() => ({}));
    return NextResponse.json(data, { status: res.status });
  } catch (err) {
    console.error("ai cancel failed:", err);
    return NextResponse.json({ error: "ai backend unavailable" }, { status: 502 });
  }
}
