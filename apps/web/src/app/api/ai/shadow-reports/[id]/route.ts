/**
 * 影子报告代理（整页 HTML / PDF）
 * GET /api/ai/shadow-reports/[id]?format=html|pdf
 */
import { vibeTradingFetch } from "@/lib/vibe-trading";

export const dynamic = "force-dynamic";

type Ctx = { params: Promise<{ id: string }> };

export async function GET(request: Request, ctx: Ctx) {
  const { id } = await ctx.params;
  const format = new URL(request.url).searchParams.get("format") ?? "html";
  if (format !== "html" && format !== "pdf") {
    return new Response("invalid format", { status: 400 });
  }
  try {
    const upstream = await vibeTradingFetch(`/shadow-reports/${id}?format=${format}`);
    if (!upstream.ok || !upstream.body) {
      return new Response(`shadow report ${upstream.status}`, { status: upstream.status });
    }
    return new Response(upstream.body, {
      headers: {
        "Content-Type":
          upstream.headers.get("Content-Type") ??
          (format === "pdf" ? "application/pdf" : "text/html; charset=utf-8"),
      },
    });
  } catch (err) {
    console.error("shadow report proxy failed:", err);
    return new Response("ai backend unavailable", { status: 502 });
  }
}
