/**
 * 因子挖掘候选 API 路由
 * GET /api/quant/mining
 * 代理 quant 容器（挖掘出的候选因子/策略），失败降级返回空数组
 */
import { NextResponse } from "next/server";
import { requireSessionUser } from "@/app/api/_guard";
import { quantFetch } from "@/lib/quant";

export async function GET() {
  const user = await requireSessionUser();
  if (user instanceof NextResponse) return user;
  try {
    const res = await quantFetch(user, `/api/mining/candidates`, {
      headers: { Accept: "application/json" },
      cache: "no-store",
    });
    if (!res.ok) {
      return NextResponse.json([]);
    }
    return NextResponse.json(await res.json());
  } catch (err) {
    console.error("quant mining proxy failed:", err);
    return NextResponse.json([]);
  }
}
