/**
 * 用户会话（server-only）：浏览器侧只持有 httpOnly cookie（tdk_session），
 * 真正的校验由 tradeck 自建 api 服务 的 /api/auth/session 完成（BFF 模式）。
 * 双后端分离：auth 走 tradeck api 服务（AUTH_API_URL），行情走 tradb data-api
 * （BACKEND_API_URL，见 lib/openbb.ts）。
 *
 * 本模块仅允许在 Server Component / Route Handler（Node 运行时）中调用，
 * 严禁在 "use client" 组件中引用——service token 不能进浏览器包。
 * （依赖中无 server-only 包，以注释标记约束；如需编译期强制可后续引入。）
 */
import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { serviceAuthHeaders } from "@/lib/service-auth";

export const SESSION_COOKIE = "tdk_session";
/** session cookie 有效期：7 天 */
export const SESSION_MAX_AGE = 7 * 24 * 60 * 60;

// 默认兜底仅供本地开发；生产由环境变量注入 tradeck api 服务 地址
// （compose 固定为 http://api:8080，容器网络直达）。
const AUTH_API = process.env.AUTH_API_URL ?? "http://localhost:8080";

export interface SessionUser {
  id: number;
  email: string;
  display_name: string | null;
  role: string;
}

/**
 * 读取当前登录用户：
 * 无 cookie → null；backend 返回 401 / 网络错误 → null（优雅降级，页面仍可渲染）。
 */
export async function getSession(): Promise<SessionUser | null> {
  const store = await cookies();
  const token = store.get(SESSION_COOKIE)?.value;
  if (!token) return null;

  try {
    const res = await fetch(`${AUTH_API}/api/auth/session`, {
      method: "POST",
      headers: {
        "X-Session-Token": token,
        Accept: "application/json",
        ...serviceAuthHeaders(),
      },
      cache: "no-store",
    });
    if (!res.ok) return null;
    const data = (await res.json()) as { user?: SessionUser };
    return data.user ?? null;
  } catch {
    return null;
  }
}

/** 要求已登录：无 session 直接跳转登录页（Server Component / Route Handler 内使用）。 */
export async function requireUser(): Promise<SessionUser> {
  const user = await getSession();
  if (!user) redirect("/login");
  return user;
}
