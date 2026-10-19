/**
 * quant 量化引擎的服务端 fetch 封装（仅 /api/quant/* 代理路由使用）。
 *
 * 统一注入两类身份（docs/MCP.md「P0 quant 加固」）：
 * - 消费方服务令牌：复用 serviceAuthHeaders()（TRADB_SERVICE_TOKEN，与 AUTH.md
 *   「web 复用同一把令牌」的取舍一致），quant 侧 INBOUND_SERVICE_TOKENS 映射为 web-bff；
 * - 当前登录用户 X-User-Id: u<auth.users.id>：quant 按此做用户命名空间隔离，
 *   与 mcp 服务同口径（同一用户经 web / MCP 看到同一套策略）。
 *
 * 安全：仅服务端（Route Handler，Node 运行时）调用，严禁在 "use client" 组件中引用。
 */
import type { SessionUser } from "@/lib/auth";
import { serviceAuthHeaders } from "@/lib/service-auth";

// 默认兜底仅供本地开发；生产由 compose 注入 http://quant:8083（容器网络直达）
const QUANT_API_URL = process.env.QUANT_API_URL ?? "http://localhost:8083";

/** 任务 id 形态（quant 任务注册表 uuid4().hex）：动态路由参数先过此白名单 */
export const TASK_ID_RE = /^[0-9a-f]{32}$/;

/** quant 侧用户 id：u + auth.users.id（满足 quant ^[A-Za-z0-9_-]{1,32}$ 白名单）。 */
export function quantUserId(user: SessionUser): string {
  return `u${user.id}`;
}

/**
 * 以当前用户身份调用 quant（path 以 /api/ 开头），默认 no-store。
 *
 * path 中的动态段必须由调用方先做白名单校验 + encodeURIComponent；这里再兜底拒绝
 * `..` / `?` / `#` / 反斜杠：动态路由参数经 Next 解码后若含 `../`，fetch 会规范化点段，
 * BFF 就会带着服务令牌去访问 quant 上未代理的任意端点。
 */
export function quantFetch(
  user: SessionUser,
  path: string,
  init: RequestInit = {}
): Promise<Response> {
  if (!path.startsWith("/api/") || /\.\.|[?#\\]/.test(path)) {
    return Promise.resolve(
      Response.json({ detail: "非法 quant 路径" }, { status: 400 })
    );
  }
  const headers = new Headers(init.headers);
  for (const [key, value] of Object.entries(serviceAuthHeaders())) {
    headers.set(key, value);
  }
  headers.set("X-User-Id", quantUserId(user));
  return fetch(`${QUANT_API_URL}${path}`, {
    cache: "no-store",
    ...init,
    headers,
  });
}
