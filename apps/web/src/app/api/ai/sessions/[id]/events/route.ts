/**
 * AI 会话事件流代理（SSE）
 * GET /api/ai/sessions/[id]/events
 * server 端换一次性 ticket 拼进 VT 查询串，流式透传给浏览器 EventSource。
 * 透传 replay=active / Last-Event-ID：重新进入进行中的会话时，重放已缓冲事件，
 * 让用户看到离开期间未完成的回答内容。
 */
import { NextRequest } from "next/server";
import { vibeTradingFetch, mintSseTicket } from "@/lib/vibe-trading";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

type Ctx = { params: Promise<{ id: string }> };

export async function GET(request: NextRequest, ctx: Ctx) {
  const { id } = await ctx.params;
  try {
    const ticket = await mintSseTicket();
    const params = new URLSearchParams({ ticket });
    // 透传续传参数：replay=active 重放进行中 attempt 的缓冲事件
    const replay = request.nextUrl.searchParams.get("replay");
    if (replay) params.set("replay", replay);
    const lastEventId = request.nextUrl.searchParams.get("Last-Event-ID");
    if (lastEventId) params.set("Last-Event-ID", lastEventId);

    const upstream = await vibeTradingFetch(
      `/sessions/${id}/events?${params.toString()}`,
      { headers: { Accept: "text/event-stream" } }
    );
    if (!upstream.ok || !upstream.body) {
      return new Response(`event: error\ndata: upstream ${upstream.status}\n\n`, {
        status: 502,
        headers: { "Content-Type": "text/event-stream" },
      });
    }
    return new Response(upstream.body, {
      headers: {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache, no-transform",
        Connection: "keep-alive",
        "X-Accel-Buffering": "no",
      },
    });
  } catch (err) {
    console.error("ai events proxy failed:", err);
    return new Response(`event: error\ndata: proxy failure\n\n`, {
      status: 502,
      headers: { "Content-Type": "text/event-stream" },
    });
  }
}
