/**
 * swarm 研究运行列表代理
 * GET /api/ai/swarm/runs
 */
import { NextResponse } from "next/server";
import { vibeTradingFetch } from "@/lib/vibe-trading";

export async function GET() {
  try {
    const res = await vibeTradingFetch("/swarm/runs");
    const data = await res.json().catch(() => []);
    return NextResponse.json(data, { status: res.status });
  } catch (err) {
    console.error("ai swarm runs GET failed:", err);
    return NextResponse.json([], { status: 502 });
  }
}
