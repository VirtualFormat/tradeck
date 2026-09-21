/**
 * 策略统一保存 API 路由（导入 / 手动编辑 / AI 调整共用）
 * POST /api/quant/strategy-save
 * 代理 quant 容器（validator 全量校验后按 id 前缀落盘 ai/ 或 custom/），
 * 失败透传 4xx 校验错误或 502。
 */
import { NextRequest, NextResponse } from "next/server";
import { assertSession } from "@/app/api/_guard";

const QUANT_API_URL = process.env.QUANT_API_URL ?? "http://localhost:8083";

export async function POST(request: NextRequest) {
  const guard = await assertSession();
  if (guard) return guard;
  try {
    const body = await request.json();
    const res = await fetch(`${QUANT_API_URL}/api/strategies/save`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      cache: "no-store",
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      // 透传 quant 的校验错误（422 安全闸拒绝 / 409 builtin 只读等），前端原样展示 detail
      return NextResponse.json(data, { status: res.status });
    }
    return NextResponse.json(data);
  } catch (err) {
    console.error("quant strategy-save proxy failed:", err);
    return NextResponse.json(
      { error: "backend unavailable" },
      { status: 502 }
    );
  }
}
