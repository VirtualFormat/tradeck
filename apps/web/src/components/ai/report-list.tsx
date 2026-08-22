"use client";

/**
 * 研究报告列表 + 详情
 * 数据源：GET /api/ai/swarm/runs（含 final_report 的 swarm 研究）
 * 点选后在右侧用 report-view 渲染 markdown
 */
import { useCallback, useEffect, useState } from "react";
import { FileTextIcon } from "@phosphor-icons/react";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { EmptyState } from "@/components/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { ReportView } from "@/components/ai/report-view";
import { cn } from "@/lib/utils";

interface SwarmRunSummary {
  id: string;
  preset_name?: string;
  status?: string;
  created_at?: string;
}

interface SwarmRunDetail {
  preset_name?: string;
  status?: string;
  created_at?: string;
  final_report?: string | null;
}

export function ReportList() {
  const [runs, setRuns] = useState<SwarmRunSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [detail, setDetail] = useState<SwarmRunDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const res = await fetch("/api/ai/swarm/runs", { cache: "no-store" });
        const data = await res.json().catch(() => []);
        setRuns(Array.isArray(data) ? data : []);
      } catch {
        setRuns([]);
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const openRun = useCallback(async (id: string) => {
    setActiveId(id);
    setDetailLoading(true);
    setDetail(null);
    try {
      const res = await fetch(`/api/ai/swarm/runs/${id}`, { cache: "no-store" });
      const data = await res.json().catch(() => ({}));
      setDetail(data);
    } catch {
      setDetail(null);
    } finally {
      setDetailLoading(false);
    }
  }, []);

  return (
    <div className="flex h-full min-h-0 gap-4">
      {/* 报告列表 */}
      <aside className="w-64 shrink-0 rounded-md border bg-card">
        <div className="border-b px-3 py-2 text-xs font-medium text-muted-foreground">
          研究报告
        </div>
        <ScrollArea className="h-[calc(100%-2.5rem)]">
          <div className="space-y-1.5 p-2">
            {loading ? (
              Array.from({ length: 4 }).map((_, i) => (
                <Skeleton key={i} className="h-14 w-full" />
              ))
            ) : runs.length === 0 ? (
              <EmptyState
                compact
                title="暂无研究报告"
                description="在问答中发起一次多智能体研究后，报告会出现在这里"
              />
            ) : (
              runs.map((r) => (
                <Card
                  key={r.id}
                  onClick={() => openRun(r.id)}
                  className={cn(
                    "cursor-pointer p-2.5 transition-colors hover:bg-muted/60",
                    r.id === activeId && "border-primary/50 bg-muted/60"
                  )}
                >
                  <div className="flex items-center gap-1.5">
                    <FileTextIcon className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                    <span className="truncate text-xs font-medium">
                      {r.preset_name ?? "研究报告"}
                    </span>
                  </div>
                  <div className="mt-1.5 flex items-center gap-1.5">
                    {r.status && (
                      <Badge variant="outline" className="text-[10px]">
                        {r.status}
                      </Badge>
                    )}
                    {r.created_at && (
                      <span className="text-[10px] text-muted-foreground">
                        {r.created_at.slice(0, 10)}
                      </span>
                    )}
                  </div>
                </Card>
              ))
            )}
          </div>
        </ScrollArea>
      </aside>

      {/* 报告详情 */}
      <div className="min-w-0 flex-1 rounded-md border bg-card">
        {detailLoading ? (
          <div className="space-y-3 p-6">
            <Skeleton className="h-6 w-1/3" />
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-5/6" />
            <Skeleton className="h-4 w-2/3" />
          </div>
        ) : detail?.final_report ? (
          <ReportView
            presetName={detail.preset_name}
            status={detail.status}
            createdAt={detail.created_at}
            report={detail.final_report}
          />
        ) : (
          <EmptyState
            title={activeId ? "该研究暂无报告内容" : "选择左侧报告查看"}
            description={activeId ? undefined : "研究报告以 Markdown 渲染"}
            className="py-20"
          />
        )}
      </div>
    </div>
  );
}
