/**
 * 因子挖掘发布 API 路由
 * POST /api/quant/mining/publish
 * 代理 quant 容器（把挖掘候选发布为策略），失败返回 502
 */
import { NextRequest, NextResponse } from "next/server";
import { requireSessionUser } from "@/app/api/_guard";
import { quantFetch } from "@/lib/quant";

export async function POST(request: NextRequest) {
  const user = await requireSessionUser();
  if (user instanceof NextResponse) return user;
  try {
    const body = await request.json();
    const res = await quantFetch(user, `/api/mining/publish`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify(body),
      cache: "no-store",
    });
    if (!res.ok) {
      // 4xx（429 在途任务超限 / 422 参数非法 / 404 策略不存在）原样透传 detail，
      // 前端据此提示且不回退旧接口；其余（5xx/网关）统一 502
      if (res.status >= 400 && res.status < 500) {
        const data = await res.json().catch(() => ({}));
        return NextResponse.json(data, { status: res.status });
      }
      return NextResponse.json(
        { error: "backend unavailable" },
        { status: 502 }
      );
    }
    return NextResponse.json(await res.json());
  } catch (err) {
    console.error("quant mining publish proxy failed:", err);
    return NextResponse.json(
      { error: "backend unavailable" },
      { status: 502 }
    );
  }
}
