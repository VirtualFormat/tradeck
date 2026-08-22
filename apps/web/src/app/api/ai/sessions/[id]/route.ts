/**
 * 单个 AI 会话操作代理
 * DELETE /api/ai/sessions/[id]  删除会话
 */
import { NextResponse } from "next/server";
import { vibeTradingFetch } from "@/lib/vibe-trading";

type Ctx = { params: Promise<{ id: string }> };

export async function DELETE(_request: Request, ctx: Ctx) {
  const { id } = await ctx.params;
  try {
    const res = await vibeTradingFetch(`/sessions/${id}`, { method: "DELETE" });
    const data = await res.json().catch(() => ({}));
    return NextResponse.json(data, { status: res.status });
  } catch (err) {
    console.error("ai session DELETE failed:", err);
    return NextResponse.json({ error: "ai backend unavailable" }, { status: 502 });
  }
}
