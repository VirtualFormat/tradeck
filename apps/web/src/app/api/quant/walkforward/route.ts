/**
 * 步进优化 API 路由
 * POST /api/quant/walkforward
 * 代理 quant 容器（walk-forward）：422 透传 detail；其他非 2xx 尝试透传后端
 * detail（P1-1：结构化 500 的原因不能被抹成笼统 502），无 detail 才 502
 */
import { NextRequest, NextResponse } from "next/server";
import { requireSessionUser } from "@/app/api/_guard";
import { quantFetch } from "@/lib/quant";

export async function POST(request: NextRequest) {
  const user = await requireSessionUser();
  if (user instanceof NextResponse) return user;
  try {
    const body = await request.json();
    const res = await quantFetch(user, `/api/walkforward`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify(body),
      cache: "no-store",
    });
    if (!res.ok) {
      const data = await res.json().catch(() => null);
      if (data?.detail) {
        return NextResponse.json(
          { detail: data.detail },
          { status: res.status }
        );
      }
      return NextResponse.json(
        { error: "backend unavailable" },
        { status: 502 }
      );
    }
    return NextResponse.json(await res.json());
  } catch (err) {
    console.error("quant walkforward proxy failed:", err);
    return NextResponse.json(
      { error: "backend unavailable" },
      { status: 502 }
    );
  }
}
