/**
 * Vibe-Trading API 客户端（server-only）
 * - 仅供 Next API 路由 / Server Component 使用，浏览器不直连
 * - VT 服务跑在独立 devcontainer（宿主机 8899），web 容器经 host.docker.internal 访问
 * - 鉴权：server 端注入 API_AUTH_KEY，浏览器永远拿不到
 */

const VT_BASE =
  process.env.VIBE_TRADING_API_URL ?? "http://host.docker.internal:8899";
const VT_KEY = process.env.VIBE_TRADING_API_KEY ?? "";

/** 带鉴权的 VT 请求，返回原始 Response（供 JSON 或流式透传） */
export async function vibeTradingFetch(
  path: string,
  init: RequestInit = {}
): Promise<Response> {
  const res = await fetch(`${VT_BASE}${path}`, {
    ...init,
    headers: {
      Authorization: `Bearer ${VT_KEY}`,
      "Content-Type": "application/json",
      Accept: "application/json",
      ...init.headers,
    },
    cache: "no-store",
  });
  return res;
}

/** 换取一次性 SSE ticket（约 60s 有效，单次使用） */
export async function mintSseTicket(): Promise<string> {
  const res = await vibeTradingFetch("/auth/sse-ticket", { method: "POST" });
  if (!res.ok) throw new Error(`sse-ticket failed: ${res.status}`);
  const data = (await res.json()) as { ticket?: string };
  if (!data.ticket) throw new Error("sse-ticket missing");
  return data.ticket;
}
