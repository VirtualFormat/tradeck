/**
 * API 令牌（PAT）BFF 共用转发：/api/account/tokens/* → tradeck api 服务 /api/auth/tokens/*。
 *
 * 流程：requireSessionUser() 先拦 401（远端校验 session）；再从 httpOnly cookie
 * 取 session token 转发为 X-Session-Token（api 侧按它识别「本人」），并带
 * serviceAuthHeaders() 消费方令牌。上游状态码与 JSON（含 detail）原样透传，
 * 网络失败 / 超时 502；响应一律 Cache-Control: no-store（签发响应含明文）。
 *
 * /api/account 不在 middleware 豁免名单内，未登录请求在 middleware 层即被拦截。
 */
import { cookies } from "next/headers";
import { NextResponse } from "next/server";

import { requireSessionUser } from "@/app/api/_guard";
import { SESSION_COOKIE } from "@/lib/auth";
import { serviceAuthHeaders } from "@/lib/service-auth";

// 默认兜底仅供本地开发；生产由环境变量注入 tradeck api 服务 地址。
const AUTH_API = process.env.AUTH_API_URL ?? "http://localhost:8080";
// 上游超时：api 服务挂起时尽快 502，不让浏览器请求无限等待
const UPSTREAM_TIMEOUT_MS = 10_000;
// 签发响应含一次性明文令牌、列表含令牌元数据：禁止浏览器 / 中间层缓存
const NO_STORE_HEADERS = { "Cache-Control": "no-store" };

export async function proxyTokens(
  path: string,
  init: { method: "GET" | "POST" | "DELETE"; body?: unknown }
): Promise<NextResponse> {
  const user = await requireSessionUser();
  if (user instanceof NextResponse) return user;

  const store = await cookies();
  const sessionToken = store.get(SESSION_COOKIE)?.value;
  if (!sessionToken) {
    return NextResponse.json({ error: "未登录或会话已过期" }, { status: 401 });
  }

  const headers: Record<string, string> = {
    Accept: "application/json",
    "X-Session-Token": sessionToken,
    ...serviceAuthHeaders(),
  };
  if (init.body !== undefined) headers["Content-Type"] = "application/json";

  let res: Response;
  try {
    res = await fetch(`${AUTH_API}/api/auth/tokens${path}`, {
      method: init.method,
      headers,
      body: init.body === undefined ? undefined : JSON.stringify(init.body),
      cache: "no-store",
      signal: AbortSignal.timeout(UPSTREAM_TIMEOUT_MS),
    });
  } catch (err) {
    console.error(`account tokens ${init.method} proxy failed:`, err);
    return NextResponse.json(
      { detail: "令牌服务不可用，请稍后重试" },
      { status: 502, headers: NO_STORE_HEADERS }
    );
  }

  const data: unknown = await res.json().catch(() => null);
  return NextResponse.json(data ?? { detail: "令牌服务返回异常" }, {
    status: data === null && res.ok ? 502 : res.status,
    headers: NO_STORE_HEADERS,
  });
}
