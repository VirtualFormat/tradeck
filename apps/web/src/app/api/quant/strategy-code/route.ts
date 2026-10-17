/**
 * 策略源码读取 API 路由（AI 工作台「加载已有策略」）
 * GET /api/quant/strategy-code?id=<strategy_id>
 * 代理 quant 容器，失败返回 404/502
 */
import { NextRequest, NextResponse } from "next/server";
import { assertSession } from "@/app/api/_guard";

const QUANT_API_URL = process.env.QUANT_API_URL ?? "http://localhost:8083";

export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  const guard = await assertSession();
  if (guard) return guard;
  const id = request.nextUrl.searchParams.get("id") ?? "";
  if (!/^[A-Za-z][A-Za-z0-9_]{0,63}$/.test(id)) {
    return NextResponse.json({ error: "非法策略 id" }, { status: 400 });
  }
  try {
    const res = await fetch(
      `${QUANT_API_URL}/api/strategies/${encodeURIComponent(id)}/code`,
      { headers: { Accept: "application/json" }, cache: "no-store" }
    );
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      return NextResponse.json(data, { status: res.status });
    }
    return NextResponse.json(data);
  } catch (err) {
    console.error("quant strategy-code proxy failed:", err);
    return NextResponse.json(
      { error: "backend unavailable" },
      { status: 502 }
    );
  }
}
