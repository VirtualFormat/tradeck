/**
 * 数据任务状态 API 代理（转发到 collector——任务运行记录/调度属写者进程内状态）
 * GET /api/system/jobs
 */
import { NextResponse } from "next/server";

import { serviceAuthHeaders } from "@/lib/service-auth";

// 默认兜底仅供本地开发；生产由环境变量注入 tradb collector 回环地址。
const COLLECTOR_API_URL =
  process.env.COLLECTOR_API_URL ?? "http://localhost:8082";

export async function GET() {
  try {
    const res = await fetch(`${COLLECTOR_API_URL}/api/system/jobs`, {
      headers: { Accept: "application/json", ...serviceAuthHeaders() },
      cache: "no-store",
    });
    if (!res.ok) {
      return NextResponse.json([], { status: res.status });
    }
    return NextResponse.json(await res.json());
  } catch (err) {
    console.error("system jobs proxy failed:", err);
    return NextResponse.json([], { status: 502 });
  }
}
