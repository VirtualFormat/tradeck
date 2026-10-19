/**
 * AI 生成任务取消 API 路由（后端幂等）
 * POST /api/quant/ai-task/[id]/cancel
 * 代理 quant 容器，失败返回 502
 */
import { NextRequest, NextResponse } from "next/server";
import { requireSessionUser } from "@/app/api/_guard";
import { TASK_ID_RE, quantFetch } from "@/lib/quant";

type Ctx = { params: Promise<{ id: string }> };

export async function POST(_request: NextRequest, ctx: Ctx) {
  const user = await requireSessionUser();
  if (user instanceof NextResponse) return user;
  const { id } = await ctx.params;
  if (!TASK_ID_RE.test(id)) {
    return NextResponse.json({ detail: "生成任务不存在" }, { status: 404 });
  }
  try {
    const res = await quantFetch(user, `/api/ai/task/${id}/cancel`, {
      method: "POST",
      headers: { Accept: "application/json" },
      cache: "no-store",
    });
    if (!res.ok) {
      return NextResponse.json(
        { error: "backend unavailable" },
        { status: 502 }
      );
    }
    return NextResponse.json(await res.json());
  } catch (err) {
    console.error("quant ai task cancel proxy failed:", err);
    return NextResponse.json(
      { error: "backend unavailable" },
      { status: 502 }
    );
  }
}
