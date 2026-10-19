/**
 * 因子编译预览 API 路由
 * POST /api/quant/factors/compile-preview
 * 代理 quant 容器（DSL 编译诊断 + 样例数据预览），失败返回 502
 */
import { NextRequest, NextResponse } from "next/server";
import { requireSessionUser } from "@/app/api/_guard";
import { quantFetch } from "@/lib/quant";

export async function POST(request: NextRequest) {
  const user = await requireSessionUser();
  if (user instanceof NextResponse) return user;
  try {
    const body = await request.json();
    const res = await quantFetch(user, `/api/factors/compile-preview`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify(body),
      cache: "no-store",
    });
    if (!res.ok) {
      const data = (await res.json().catch(() => null)) as {
        detail?: string;
      } | null;
      return NextResponse.json(
        { error: data?.detail ?? "backend unavailable" },
        { status: res.status }
      );
    }
    return NextResponse.json(await res.json());
  } catch (err) {
    console.error("quant factors compile-preview proxy failed:", err);
    return NextResponse.json(
      { error: "backend unavailable" },
      { status: 502 }
    );
  }
}
