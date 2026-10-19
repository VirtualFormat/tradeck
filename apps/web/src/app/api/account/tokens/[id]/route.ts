/**
 * API 令牌撤销（BFF 转发）
 * DELETE /api/account/tokens/[id] → 撤销本人令牌（他人/不存在 404）
 * 转发 tradeck api 服务 /api/auth/tokens/{id}，透传状态码与 JSON（含 detail）。
 */
import { NextRequest, NextResponse } from "next/server";

import { proxyTokens } from "../_proxy";

type RouteContext = { params: Promise<{ id: string }> };

export async function DELETE(_request: NextRequest, context: RouteContext) {
  const { id } = await context.params;
  // 仅接受正整数 id，避免任意路径片段拼进上游 URL
  if (!/^[1-9]\d{0,18}$/.test(id)) {
    return NextResponse.json({ detail: "令牌不存在" }, { status: 404 });
  }
  return proxyTokens(`/${id}`, { method: "DELETE" });
}
