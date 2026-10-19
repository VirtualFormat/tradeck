/**
 * 策略列表 API 路由
 * GET /api/quant/strategies
 * 代理 quant 容器（已保存策略列表），失败降级返回空数组
 */
import { NextResponse } from "next/server";
import { requireSessionUser } from "@/app/api/_guard";
import { quantFetch } from "@/lib/quant";

export async function GET() {
  const user = await requireSessionUser();
  if (user instanceof NextResponse) return user;
  try {
    const res = await quantFetch(user, `/api/strategies`, {
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
