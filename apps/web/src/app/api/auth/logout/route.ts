/**
 * 登出 API 路由（BFF 转发）
 * POST /api/auth/logout
 * 通知 tradeck api 服务 作废 token，并删除本地 httpOnly cookie。
 * api 服务不可达时也照常删 cookie（本地登出必然成功）。
 */
import { NextRequest, NextResponse } from "next/server";

import { SESSION_COOKIE } from "@/lib/auth";
import { serviceAuthHeaders } from "@/lib/service-auth";

// 默认兜底仅供本地开发；生产由环境变量注入 tradeck api 服务 地址。
const AUTH_API = process.env.AUTH_API_URL ?? "http://localhost:8080";

export async function POST(request: NextRequest) {
  const token = request.cookies.get(SESSION_COOKIE)?.value;

  if (token) {
    try {
      await fetch(`${AUTH_API}/api/auth/logout`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "application/json",
          ...serviceAuthHeaders(),
        },
        body: JSON.stringify({ token }),
        cache: "no-store",
      });
    } catch (err) {
      console.error("logout notify api failed:", err);
    }
  }

  const response = NextResponse.json({ ok: true });
  response.cookies.set(SESSION_COOKIE, "", {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    maxAge: 0,
  });
  return response;
}
