/**
 * 登录 API 路由（BFF 转发）
 * POST /api/auth/login {email, password}
 * 转发 tradeck api 服务 /api/auth/login；成功则把 token 写入 httpOnly cookie。
 *
 * 说明：明文密码经同站 POST 到本路由，再在服务端转发 api 服务，
 * 浏览器不直连 api 服务；P2 上 HTTPS 后传输链路闭环。
 */
import { NextRequest, NextResponse } from "next/server";

import { SESSION_COOKIE, SESSION_MAX_AGE } from "@/lib/auth";
import { serviceAuthHeaders } from "@/lib/service-auth";

// 默认兜底仅供本地开发；生产由环境变量注入 tradeck api 服务 地址。
const AUTH_API = process.env.AUTH_API_URL ?? "http://localhost:8080";

/**
 * 取真实客户端 IP 注入 X-Forwarded-For（api 服务登录限流按来源计数）。
 * 优先取入站 x-forwarded-for 最左值（反代注入的原始客户端），其次 x-real-ip；
 * 都取不到则不加该头——无反代时 BFF 直连场景 backend 会回退 client.host。
 */
function clientIpHeaders(request: NextRequest): Record<string, string> {
  const forwardedFor = request.headers.get("x-forwarded-for");
  const ip = forwardedFor?.split(",")[0]?.trim() || request.headers.get("x-real-ip");
  return ip ? { "X-Forwarded-For": ip } : {};
}

export async function POST(request: NextRequest) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "请求格式错误" }, { status: 400 });
  }

  try {
    const res = await fetch(`${AUTH_API}/api/auth/login`, {
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
      let error = "登录失败，请稍后重试";
      if (res.status === 401) {
        error = "邮箱或密码错误";
      } else if (res.status === 429) {
        // 限流：透传 backend 的 detail 文案（含剩余冷却时间等信息）
        const detail = (data as { detail?: unknown } | null)?.detail;
        if (typeof detail === "string" && detail) error = detail;
      }
      return NextResponse.json({ error }, { status: res.status });
    }

    const session = data as {
      token?: string;
      expires_at?: string;
      user?: unknown;
    };
    if (!session?.token) {
      return NextResponse.json(
        { error: "登录失败，请稍后重试" },
        { status: 502 }
      );
    }

    const response = NextResponse.json({ user: session.user ?? null });
    response.cookies.set(SESSION_COOKIE, session.token, {
      httpOnly: true,
      secure: process.env.NODE_ENV === "production",
      sameSite: "lax",
      path: "/",
      maxAge: SESSION_MAX_AGE,
    });
    return response;
  } catch (err) {
    console.error("login proxy failed:", err);
    return NextResponse.json(
      { error: "登录失败，请稍后重试" },
      { status: 502 }
    );
  }
}
