/**
 * AI 消息代理
 * POST /api/ai/sessions/[id]/messages  发消息（启动 agent loop）
 * GET  /api/ai/sessions/[id]/messages  历史消息
 */
import { NextRequest, NextResponse } from "next/server";
import { vibeTradingFetch } from "@/lib/vibe-trading";

type Ctx = { params: Promise<{ id: string }> };

export async function POST(request: NextRequest, ctx: Ctx) {
  const { id } = await ctx.params;
  try {
    const body = await request.json();
    const res = await vibeTradingFetch(`/sessions/${id}/messages`, {
      method: "POST",
      body: JSON.stringify(body),
    });
    const data = await res.json().catch(() => ({}));
    return NextResponse.json(data, { status: res.status });
  } catch (err) {
    console.error("ai messages POST failed:", err);
    return NextResponse.json({ error: "ai backend unavailable" }, { status: 502 });
  }
}

export async function GET(request: NextRequest, ctx: Ctx) {
  const { id } = await ctx.params;
  const limit = request.nextUrl.searchParams.get("limit") ?? "100";
  try {
    const res = await vibeTradingFetch(`/sessions/${id}/messages?limit=${limit}`);
    const data = await res.json().catch(() => []);
    return NextResponse.json(data, { status: res.status });
  } catch (err) {
    console.error("ai messages GET failed:", err);
    return NextResponse.json([], { status: 502 });
  }
}
