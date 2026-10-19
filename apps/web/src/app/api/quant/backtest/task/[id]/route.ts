/**
 * 任务化回测进度查询 API 路由（阶段 K4）
 * GET /api/quant/backtest/task/[id] → { status, progress?, result?, error? }
 * 代理 quant 容器，失败返回 502（前端轮询层负责重试计数）
 */
import { NextRequest, NextResponse } from "next/server";
import { requireSessionUser } from "@/app/api/_guard";
import { TASK_ID_RE, quantFetch } from "@/lib/quant";

type Ctx = { params: Promise<{ id: string }> };

export async function GET(_request: NextRequest, ctx: Ctx) {
  const user = await requireSessionUser();
  if (user instanceof NextResponse) return user;
  const { id } = await ctx.params;
  if (!TASK_ID_RE.test(id)) {
    return NextResponse.json({ detail: "回测任务不存在" }, { status: 404 });
  }
  try {
    const res = await quantFetch(user, `/api/backtest/task/${id}`, {
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
    console.error("quant backtest task proxy failed:", err);
    return NextResponse.json(
      { error: "backend unavailable" },
      { status: 502 }
    );
  }
}
