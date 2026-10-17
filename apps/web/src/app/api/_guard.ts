/**
 * 代理路由会话守卫：所有 /api/* 代理路由（/api/auth/* 除外）在转发前调用。
 *
 * 与 middleware.ts 的分工：middleware 只检查 cookie 存在与否（不打 backend），
 * 这里做远端校验（cookie 值经 backend /api/auth/session 验证），挡住
 * 伪造 / 过期 / 已登出的 token。
 *
 * 返回 null 表示通过；未通过直接返回 401 Response，route handler 应原样 return。
 */
import { NextResponse } from "next/server";

import { getSession } from "@/lib/auth";

export async function assertSession(): Promise<NextResponse | null> {
  const user = await getSession();
  if (user) return null;
  return NextResponse.json({ error: "未登录或会话已过期" }, { status: 401 });
}
