/**
 * 注册 API 路由（BFF 转发）
 * POST /api/auth/register {email, password, display_name?, invite_token?}
 * 状态码语义透传：403=邀请码错误，409=邮箱已注册。
 *
 * 说明：明文密码经同站 POST 到本路由，再在服务端转发 tradeck auth-api，
 * 浏览器不直连 auth-api；P2 上 HTTPS 后传输链路闭环。
 */
import { NextRequest, NextResponse } from "next/server";

import { SESSION_COOKIE, SESSION_MAX_AGE } from "@/lib/auth";
import { serviceAuthHeaders } from "@/lib/service-auth";

// 默认兜底仅供本地开发；生产由环境变量注入 tradeck auth-api 地址。
const AUTH_API = process.env.AUTH_API_URL ?? "http://localhost:8080";

/**
 * 取真实客户端 IP 注入 X-Forwarded-For（auth-api 登录限流按来源计数）。
 * 优先取入站 x-forwarded-for 最左值（反代注入的原始客户端），其次 x-real-ip；
 * 都取不到则不加该头——无反代时 BFF 直连场景 backend 会回退 client.host。
 */
function clientIpHeaders(request: NextRequest): Record<string, string> {
  const forwardedFor = request.headers.get("x-forwarded-for");
  const ip =
    forwardedFor?.split(",")[0]?.trim() || request.headers.get("x-real-ip");
  return ip ? { "X-Forwarded-For": ip } : {};
}

/**
 * 注册成功后的自动登录：向 auth-api 发 login 请求拿 session token。
 * 失败（网络/限流/非 200）返回 null，由调用方降级为「注册成功，请登录」。
 */
async function loginForSession(
  credentials: { email: string; password: string },
  request: NextRequest
): Promise<{ token: string; user?: unknown } | null> {
  try {
    const res = await fetch(`${AUTH_API}/api/auth/login`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
        ...clientIpHeaders(request),
        ...serviceAuthHeaders(),
      },
      body: JSON.stringify(credentials),
      cache: "no-store",
    });
    const data: unknown = await res.json().catch(() => null);
    if (!res.ok) return null;
    const session = data as { token?: string; user?: unknown } | null;
    if (!session?.token) return null;
    return { token: session.token, user: session.user };
  } catch (err) {
    console.error("register auto-login failed:", err);
    return null;
  }
}

export async function POST(request: NextRequest) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "请求格式错误" }, { status: 400 });
  }

  // 自动登录只认 email + password 两个字段（注册入参不整包转发给 login）
  const credentials =
    body !== null &&
    typeof body === "object" &&
    typeof (body as { email?: unknown }).email === "string" &&
    typeof (body as { password?: unknown }).password === "string"
      ? {
          email: (body as { email: string }).email,
          password: (body as { password: string }).password,
        }
      : null;

  try {
    const res = await fetch(`${AUTH_API}/api/auth/register`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
        ...clientIpHeaders(request),
        ...serviceAuthHeaders(),
      },
      body: JSON.stringify(body),
      cache: "no-store",
    });

    const data: unknown = await res.json().catch(() => null);

    if (!res.ok) {
      let error = "注册失败，请稍后重试";
      if (res.status === 403) error = "邀请码错误";
      if (res.status === 409) error = "该邮箱已注册";
      return NextResponse.json({ error }, { status: res.status });
    }

    const payload =
      typeof data === "object" && data !== null ? data : { ok: true };

    // 注册成功 → 同一 handler 内自动登录，像 login 路由一样种 tdk_session cookie；
    // 自动登录失败（极端情况）仍算注册成功，但提示前端走手动登录。
    if (credentials) {
      const session = await loginForSession(credentials, request);
      if (session) {
        const response = NextResponse.json(
          { ...payload, user: session.user ?? null },
          { status: res.status }
        );
        response.cookies.set(SESSION_COOKIE, session.token, {
          httpOnly: true,
          secure: process.env.NODE_ENV === "production",
          sameSite: "lax",
          path: "/",
          maxAge: SESSION_MAX_AGE,
        });
        return response;
      }
    }
    return NextResponse.json(
      { ...payload, message: "注册成功，请登录" },
      { status: res.status }
    );
  } catch (err) {
    console.error("register proxy failed:", err);
    return NextResponse.json(
      { error: "注册失败，请稍后重试" },
      { status: 502 }
    );
  }
}
