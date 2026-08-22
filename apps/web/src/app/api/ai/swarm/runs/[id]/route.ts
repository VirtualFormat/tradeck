/**
 * swarm 运行详情代理（含 final_report markdown）
 * GET /api/ai/swarm/runs/[id]
 */
import { NextResponse } from "next/server";
import { vibeTradingFetch } from "@/lib/vibe-trading";

type Ctx = { params: Promise<{ id: string }> };

export async function GET(_request: Request, ctx: Ctx) {
  const { id } = await ctx.params;
  try {
    const res = await vibeTradingFetch(`/swarm/runs/${id}`);
    const data = await res.json().catch(() => ({}));
    return NextResponse.json(data, { status: res.status });
  } catch (err) {
    console.error("ai swarm run GET failed:", err);
    return NextResponse.json({ error: "ai backend unavailable" }, { status: 502 });
  }
}
