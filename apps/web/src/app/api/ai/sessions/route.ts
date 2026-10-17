/**
 * AI 会话代理
 * POST /api/ai/sessions  建会话
 * GET  /api/ai/sessions  会话列表
 */
import { NextRequest, NextResponse } from "next/server";
import { vibeTradingFetch } from "@/lib/vibe-trading";
import { assertSession } from "@/app/api/_guard";

export async function POST(request: NextRequest) {
  const guard = await assertSession();
  if (guard) return guard;
  try {
    const body = await request.json().catch(() => ({}));
    const res = await vibeTradingFetch("/sessions", {
      method: "POST",
      body: JSON.stringify(body),
    });
    const data = await res.json().catch(() => ({}));
    return NextResponse.json(data, { status: res.status });
  } catch (err) {
    console.error("ai sessions POST failed:", err);
    return NextResponse.json({ error: "ai backend unavailable" }, { status: 502 });
  }
}

export async function GET() {
  const guard = await assertSession();
  if (guard) return guard;
  try {
    const res = await vibeTradingFetch("/sessions");
    const data = await res.json().catch(() => []);
    return NextResponse.json(data, { status: res.status });
  } catch (err) {
    console.error("ai sessions GET failed:", err);
    return NextResponse.json([], { status: 502 });
  }
}
