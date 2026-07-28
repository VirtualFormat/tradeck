/**
 * 数据同步状态条（客户端组件，轮询 /api/system/jobs）
 * - 有任务运行中：进度条 + 计数（全量初始化/每日更新都提示）
 * - 无运行中任务：最近 24h 完成记录的一行提示；没有记录则不渲染
 */
"use client";

import { useEffect, useState } from "react";
import { format } from "date-fns";
import {
  CheckCircleIcon,
  CloudArrowDownIcon,
  WarningCircleIcon,
} from "@phosphor-icons/react";

import { type JobProgress } from "@/lib/openbb";
import { Progress } from "@/components/ui/progress";
import { Card, CardContent } from "@/components/ui/card";

const POLL_MS = 5000;
const RECENT_DONE_MS = 24 * 60 * 60 * 1000;

/** 经 Next API 路由代理 backend（客户端直连 backend 跨容器不通） */
async function fetchJobs(): Promise<JobProgress[]> {
  const res = await fetch("/api/system/jobs", { cache: "no-store" });
  if (!res.ok) return [];
  const data = await res.json();
  return Array.isArray(data) ? data : [];
}

function fmtTime(iso: string | null): string {
  if (!iso) return "";
  try {
    return format(new Date(iso), "HH:mm");
  } catch {
    return "";
  }
}

function StatusLine({ job }: { job: JobProgress }) {
  if (job.status === "error") {
    return (
      <div className="flex items-center gap-2 text-xs text-down">
        <WarningCircleIcon className="h-4 w-4 shrink-0" />
        <span>
          {job.label}失败：{job.note || "未知错误"}（下周期自动重试）
        </span>
      </div>
    );
  }
  return (
    <div className="flex items-center gap-2 text-xs text-muted-foreground">
      <CheckCircleIcon className="h-4 w-4 shrink-0 text-up" />
      <span>
        {job.label}完成于 {fmtTime(job.finished_at)}
        {job.note ? `（${job.note}）` : ""}
      </span>
    </div>
  );
}

export function DataSyncStatus() {
  const [jobs, setJobs] = useState<JobProgress[]>([]);

  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      try {
        const data = await fetchJobs();
        if (!cancelled) setJobs(data);
      } catch {
        /* 降级：拉不到就不显示 */
      }
    };
    tick();
    const timer = setInterval(tick, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);

  const running = jobs.find((j) => j.status === "running");
  const latestDone = jobs.find(
    (j) =>
      j.status === "done" &&
      j.finished_at &&
      Date.now() - new Date(j.finished_at).getTime() < RECENT_DONE_MS
  );
  const latestError = jobs.find((j) => j.status === "error");

  if (!running && !latestDone && !latestError) return null;

  return (
    <div className="px-4 lg:px-6">
      <Card className="border-border/60 py-3">
        <CardContent className="px-4">
          {running ? (
            <div className="flex items-center gap-3">
              <CloudArrowDownIcon className="h-4 w-4 shrink-0 text-accent" />
              <div className="min-w-0 flex-1">
                <div className="mb-1.5 flex items-baseline justify-between gap-2 text-xs">
                  <span className="font-medium">
                    {running.label}中，页面数据将逐步补齐
                  </span>
                  <span className="tab-nums shrink-0 text-muted-foreground">
                    {running.processed.toLocaleString()}/
                    {running.total.toLocaleString()} 只 · {running.percent}%
                  </span>
                </div>
                <Progress value={running.percent} className="h-1.5" />
              </div>
            </div>
          ) : (
            <StatusLine job={(latestError ?? latestDone) as JobProgress} />
          )}
        </CardContent>
      </Card>
    </div>
  );
}
