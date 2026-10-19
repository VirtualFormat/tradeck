/**
 * 量化选股 API 路由
 * POST /api/quant/screen
 * 代理 quant 容器（条件筛选），失败降级返回空结果
 */
import { NextRequest, NextResponse } from "next/server";
import { requireSessionUser } from "@/app/api/_guard";
import { quantFetch } from "@/lib/quant";

export async function POST(request: NextRequest) {
  const user = await requireSessionUser();
  if (user instanceof NextResponse) return user;
  try {
    const body = await request.json();
    const res = await quantFetch(user, `/api/screen`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify(body),
      cache: "no-store",
    });
    if (res.status >= 400 && res.status < 500) {
      // 参数非法 / 策略不存在 / 策略执行失败：透传 detail，避免静默显示「无入选」
      const data = await res.json().catch(() => ({}));
      return NextResponse.json(data, { status: res.status });
    }
    if (!res.ok) {
      return NextResponse.json({ rows: [], total: 0 });
    }
    return NextResponse.json(await res.json());
  } catch (err) {
    console.error("quant screen proxy failed:", err);
    return NextResponse.json({ rows: [], total: 0 });
  }
}
