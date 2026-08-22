/**
 * 手动同步 API 代理（转发到 collector——任务触发属写者进程内能力）
 * POST /api/system/jobs/:job/run
 */
import { NextRequest, NextResponse } from "next/server";

const COLLECTOR_API_URL =
  process.env.COLLECTOR_API_URL ?? "http://localhost:8082";

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ job: string }> }
) {
  const { job } = await params;
  const token = request.headers.get("x-data-sync-token") ?? "";
  try {
    const res = await fetch(
      `${COLLECTOR_API_URL}/api/system/jobs/${encodeURIComponent(job)}/run`,
      {
        method: "POST",
        headers: {
          Accept: "application/json",
          ...(token ? { "X-Data-Sync-Token": token } : {}),
        },
        cache: "no-store",
      }
    );
    const data = await res.json().catch(() => ({
      accepted: false,
      message: "后端未返回有效响应",
    }));
    return NextResponse.json(data, { status: res.status });
  } catch (err) {
    console.error(`manual sync proxy failed (${job}):`, err);
    return NextResponse.json(
      { accepted: false, message: "无法连接数据服务" },
      { status: 502 }
    );
  }
}
