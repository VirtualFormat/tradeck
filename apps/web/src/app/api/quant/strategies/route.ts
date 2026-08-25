/**
 * 策略列表 API 路由
 * GET /api/quant/strategies
 * 代理 quant 容器（已保存策略列表），失败降级返回空数组
 */
import { NextResponse } from "next/server";

const QUANT_API_URL = process.env.QUANT_API_URL ?? "http://localhost:8083";

export async function GET() {
  try {
    const res = await fetch(`${QUANT_API_URL}/api/strategies`, {
      headers: { Accept: "application/json" },
      cache: "no-store",
    });
    if (!res.ok) {
      return NextResponse.json([]);
    }
    return NextResponse.json(await res.json());
  } catch (err) {
    console.error("quant strategies proxy failed:", err);
    return NextResponse.json([]);
  }
}
