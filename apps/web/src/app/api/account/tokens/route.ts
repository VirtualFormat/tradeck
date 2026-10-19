/**
 * API 令牌列表 / 签发（BFF 转发）
 * GET  /api/account/tokens         → 本人令牌列表
 * POST /api/account/tokens {name, scopes, expires_days} → 签发（明文仅本次返回）
 * 转发 tradeck api 服务 /api/auth/tokens，透传状态码与 JSON（含 detail）。
 */
import { NextRequest, NextResponse } from "next/server";

import { proxyTokens } from "./_proxy";

export function GET() {
  return proxyTokens("", { method: "GET" });
}

export async function POST(request: NextRequest) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ detail: "请求格式错误" }, { status: 400 });
  }
  return proxyTokens("", { method: "POST", body });
}
