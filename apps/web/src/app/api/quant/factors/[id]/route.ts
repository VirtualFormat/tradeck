/**
 * 因子更新 / 删除 API 路由
 * PUT/DELETE /api/quant/factors/[id]
 * 代理 quant 容器（因子注册表），失败降级返回 502
 */
import { NextRequest, NextResponse } from "next/server";

const QUANT_API_URL = process.env.QUANT_API_URL ?? "http://localhost:8083";

type RouteContext = { params: Promise<{ id: string }> };

async function proxy(
  request: NextRequest,
  context: RouteContext,
  method: "PUT" | "DELETE"
) {
  const { id } = await context.params;
  const init: RequestInit = {
    method,
    headers: { Accept: "application/json" },
    cache: "no-store",
  };
  if (method === "PUT") {
    init.headers = {
      ...init.headers,
      "Content-Type": "application/json",
    };
    init.body = JSON.stringify(await request.json());
  }
  try {
    const res = await fetch(
      `${QUANT_API_URL}/api/factors/${encodeURIComponent(id)}`,
      init
    );
    if (!res.ok) {
      const data = (await res.json().catch(() => null)) as {
        detail?: string;
      } | null;
      return NextResponse.json(
        { error: data?.detail ?? "backend unavailable" },
        { status: res.status }
      );
    }
    return NextResponse.json(await res.json());
  } catch (err) {
    console.error(`quant factors ${method} proxy failed:`, err);
    return NextResponse.json(
      { error: "backend unavailable" },
      { status: 502 }
    );
  }
}

export function PUT(request: NextRequest, context: RouteContext) {
  return proxy(request, context, "PUT");
}

export function DELETE(request: NextRequest, context: RouteContext) {
  return proxy(request, context, "DELETE");
}
