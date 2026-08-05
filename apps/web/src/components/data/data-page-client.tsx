"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ArrowsClockwiseIcon,
  CheckCircleIcon,
  ClockCountdownIcon,
  CloudArrowDownIcon,
  DatabaseIcon,
  HardDrivesIcon,
  PulseIcon,
  RowsIcon,
  WarningCircleIcon,
} from "@phosphor-icons/react";

import {
  type DataJob,
  type DataSystemSnapshot,
  type JobProgress,
} from "@/lib/openbb";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { EmptyState } from "@/components/empty-state";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";

const POLL_MS = 3000;

const EMPTY_SNAPSHOT: DataSystemSnapshot = {
  jobs: [],
  tables: [],
  daily_markets: [],
  summary: {
    job_count: 0,
    running_count: 0,
    error_count: 0,
    table_count: 0,
    total_rows: 0,
    total_bytes: 0,
  },
};

function formatNumber(value: number): string {
  return new Intl.NumberFormat("zh-CN").format(value);
}

function formatBytes(value: number): string {
  if (!value) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const unit = Math.min(Math.floor(Math.log(value) / Math.log(1024)), 4);
  return `${(value / 1024 ** unit).toFixed(unit > 1 ? 1 : 0)} ${units[unit]}`;
}

function formatDateTime(value: string | null): string {
  if (!value) return "—";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(new Date(value));
}

function formatCompactDateTime(value: string | null): string {
  if (!value) return "—";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(value));
}

function formatDuration(run: JobProgress | null): string {
  if (!run) return "—";
  const end = run.finished_at ? new Date(run.finished_at).getTime() : Date.now();
  const seconds = Math.max(
    0,
    Math.floor((end - new Date(run.started_at).getTime()) / 1000)
  );
  if (seconds < 60) return `${seconds} 秒`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} 分 ${seconds % 60} 秒`;
  return `${Math.floor(minutes / 60)} 小时 ${minutes % 60} 分`;
}

function triggerLabel(trigger: JobProgress["trigger"] | undefined): string {
  if (trigger === "manual") return "手动";
  if (trigger === "startup") return "启动预热";
  return "定时";
}

function JobStatusBadge({ job }: { job: DataJob }) {
  if (job.status === "running") {
    return (
      <Badge variant="secondary" className="text-primary">
        <PulseIcon data-icon="inline-start" />
        运行中
      </Badge>
    );
  }
  if (job.status === "error") {
    return (
      <Badge variant="destructive">
        <WarningCircleIcon data-icon="inline-start" />
        异常
      </Badge>
    );
  }
  if (job.status === "done") {
    return (
      <Badge variant="outline">
        <CheckCircleIcon data-icon="inline-start" className="text-down" />
        已完成
      </Badge>
    );
  }
  return <Badge variant="outline">等待运行</Badge>;
}

function SummaryCard({
  label,
  value,
  description,
  icon,
}: {
  label: string;
  value: string;
  description: string;
  icon: React.ReactNode;
}) {
  return (
    <Card size="sm">
      <CardHeader>
        <CardDescription>{label}</CardDescription>
        <CardAction className="text-muted-foreground">{icon}</CardAction>
        <CardTitle className="font-mono text-2xl tabular-nums">{value}</CardTitle>
      </CardHeader>
      <CardContent className="text-xs text-muted-foreground">
        {description}
      </CardContent>
    </Card>
  );
}

function MarketCoverage({ snapshot }: { snapshot: DataSystemSnapshot }) {
  const names: Record<string, string> = {
    CN: "A 股",
    HK: "港股",
    US: "美股",
  };

  return (
    <div className="grid gap-3 md:grid-cols-3">
      {["CN", "HK", "US"].map((market) => {
        const stat = snapshot.daily_markets.find(
          (item) => item.market === market
        );
        return (
          <Card key={market} size="sm">
            <CardHeader>
              <CardTitle>{names[market]}</CardTitle>
              <CardAction>
                <Badge variant="secondary">TickFlow</Badge>
              </CardAction>
              <CardDescription>
                最新交易日 {stat?.latest_date ?? "尚无数据"}
              </CardDescription>
            </CardHeader>
            <CardContent className="flex items-end justify-between gap-3">
              <div>
                <div className="font-mono text-xl font-semibold tabular-nums">
                  {formatNumber(stat?.row_count ?? 0)}
                </div>
                <div className="mt-1 text-xs text-muted-foreground">
                  daily_prices 行数
                </div>
              </div>
              <DatabaseIcon className="size-8 text-muted-foreground/50" />
            </CardContent>
          </Card>
        );
      })}
    </div>
  );
}

function RunningPanel({ jobs }: { jobs: DataJob[] }) {
  const running = jobs.filter((job) => job.status === "running");
  if (running.length === 0) {
    return (
      <Card size="sm">
        <CardContent>
          <EmptyState compact title="当前没有运行中的数据同步任务" />
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-3">
      {running.map((job) => {
        const run = job.last_run;
        return (
          <Card key={job.id} size="sm">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <CloudArrowDownIcon className="text-primary" />
                {job.label}
              </CardTitle>
              <CardAction>
                <Badge variant="secondary">
                  {triggerLabel(run?.trigger)}触发
                </Badge>
              </CardAction>
              <CardDescription>{job.description}</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="mb-2 flex items-baseline justify-between gap-3 text-xs">
                <span className="text-muted-foreground">
                  已运行 {formatDuration(run)}
                </span>
                <span className="font-mono tabular-nums">
                  {run?.total
                    ? `${formatNumber(run.processed)} / ${formatNumber(run.total)} · ${run.percent}%`
                    : "同步中"}
                </span>
              </div>
              <Progress value={run?.percent ?? 0} />
            </CardContent>
          </Card>
        );
      })}
    </div>
  );
}

export function DataPageClient() {
  const [snapshot, setSnapshot] =
    useState<DataSystemSnapshot>(EMPTY_SNAPSHOT);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [syncToken, setSyncToken] = useState("");
  const [triggering, setTriggering] = useState<Set<string>>(new Set());
  const [notice, setNotice] = useState<{
    type: "success" | "error";
    message: string;
  } | null>(null);

  const refresh = useCallback(async () => {
    try {
      const res = await fetch("/api/system/data", { cache: "no-store" });
      if (!res.ok) throw new Error("数据服务暂不可用");
      const data = (await res.json()) as DataSystemSnapshot;
      setSnapshot({
        ...EMPTY_SNAPSHOT,
        ...data,
        summary: { ...EMPTY_SNAPSHOT.summary, ...data.summary },
      });
      setLoadError("");
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : "数据服务暂不可用");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const initialTimer = window.setTimeout(() => void refresh(), 0);
    const timer = window.setInterval(() => void refresh(), POLL_MS);
    return () => {
      window.clearTimeout(initialTimer);
      window.clearInterval(timer);
    };
  }, [refresh]);

  const manualSync = useCallback(
    async (job: DataJob) => {
      setTriggering((current) => new Set(current).add(job.id));
      setNotice(null);
      try {
        const res = await fetch(`/api/system/jobs/${job.id}/run`, {
          method: "POST",
          headers: { "X-Data-Sync-Token": syncToken },
        });
        const data = (await res.json()) as {
          accepted?: boolean;
          message?: string;
          detail?: string;
        };
        if (!res.ok || !data.accepted) {
          throw new Error(data.message || data.detail || "同步任务未能启动");
        }
        setNotice({ type: "success", message: `${job.label}已开始同步` });
        await refresh();
      } catch (error) {
        setNotice({
          type: "error",
          message: error instanceof Error ? error.message : "同步任务未能启动",
        });
      } finally {
        setTriggering((current) => {
          const next = new Set(current);
          next.delete(job.id);
          return next;
        });
      }
    },
    [refresh, syncToken]
  );

  const latestFinish = useMemo(() => {
    const values = snapshot.jobs
      .map((job) => job.last_run?.finished_at)
      .filter((value): value is string => Boolean(value))
      .sort();
    return values.at(-1) ?? null;
  }, [snapshot.jobs]);

  return (
    <div className="space-y-6 px-4 lg:px-6">
      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div>
          <h1 className="text-xl font-semibold">数据中心</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            查看 TickFlow 与其他数据源的拉取状态、库表规模和调度计划。
          </p>
        </div>
        <div className="flex flex-col gap-2 sm:flex-row">
          <Input
            type="password"
            value={syncToken}
            onChange={(event) => setSyncToken(event.target.value)}
            placeholder="输入令牌以启用手动同步"
            aria-label="手动同步令牌"
            autoComplete="off"
            className="sm:w-48"
          />
          <Button
            variant="outline"
            onClick={() => void refresh()}
            disabled={loading}
          >
            <ArrowsClockwiseIcon data-icon="inline-start" />
            刷新状态
          </Button>
        </div>
      </div>

      {loadError && (
        <Card size="sm" className="ring-destructive/30">
          <CardContent className="flex items-center gap-2 text-destructive">
            <WarningCircleIcon className="size-5" />
            {loadError}
          </CardContent>
        </Card>
      )}

      {notice && (
        <Card
          size="sm"
          className={cn(
            notice.type === "error"
              ? "ring-destructive/30"
              : "ring-primary/30"
          )}
        >
          <CardContent
            className={cn(
              "flex items-center gap-2",
              notice.type === "error" ? "text-destructive" : "text-foreground"
            )}
          >
            {notice.type === "error" ? (
              <WarningCircleIcon className="size-5" />
            ) : (
              <CheckCircleIcon className="size-5 text-down" />
            )}
            {notice.message}
          </CardContent>
        </Card>
      )}

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <SummaryCard
          label="数据任务"
          value={formatNumber(snapshot.summary.job_count)}
          description={`${snapshot.summary.running_count} 个运行中 · ${snapshot.summary.error_count} 个异常`}
          icon={<PulseIcon className="size-5" />}
        />
        <SummaryCard
          label="数据库行数"
          value={formatNumber(snapshot.summary.total_rows)}
          description={`${snapshot.summary.table_count} 张业务表`}
          icon={<RowsIcon className="size-5" />}
        />
        <SummaryCard
          label="存储占用"
          value={formatBytes(snapshot.summary.total_bytes)}
          description="PostgreSQL 表与索引总占用"
          icon={<HardDrivesIcon className="size-5" />}
        />
        <SummaryCard
          label="最近完成"
          value={latestFinish ? formatCompactDateTime(latestFinish) : "—"}
          description="状态每 3 秒自动刷新"
          icon={<ClockCountdownIcon className="size-5" />}
        />
      </div>

      <section className="space-y-3">
        <div>
          <h2 className="text-sm font-medium">TickFlow 日 K 覆盖</h2>
          <p className="mt-1 text-xs text-muted-foreground">
            全市场批量拉取，按 CN / HK / US 分市场展示当前入库规模与最新交易日。
          </p>
        </div>
        <MarketCoverage snapshot={snapshot} />
      </section>

      <section className="space-y-3">
        <div>
          <h2 className="text-sm font-medium">当前拉取状态</h2>
          <p className="mt-1 text-xs text-muted-foreground">
            日 K 显示标的级进度；其他任务显示当前运行时长。
          </p>
        </div>
        <RunningPanel jobs={snapshot.jobs} />
      </section>

      <Tabs defaultValue="jobs">
        <TabsList variant="line">
          <TabsTrigger value="jobs">同步任务</TabsTrigger>
          <TabsTrigger value="tables">数据表</TabsTrigger>
        </TabsList>

        <TabsContent value="jobs">
          <Card>
            <CardHeader>
              <CardTitle>任务目录</CardTitle>
              <CardDescription>
                手动同步在后台运行，不阻塞页面；运行中的任务不会重复启动。
              </CardDescription>
            </CardHeader>
            <CardContent className="px-0">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="pl-4">任务</TableHead>
                    <TableHead>数据源</TableHead>
                    <TableHead>状态</TableHead>
                    <TableHead>最近运行</TableHead>
                    <TableHead>下次调度</TableHead>
                    <TableHead className="text-right pr-4">操作</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {snapshot.jobs.length === 0 && (
                    <TableRow>
                      <TableCell colSpan={6}>
                        <EmptyState compact title="暂无任务状态" />
                      </TableCell>
                    </TableRow>
                  )}
                  {snapshot.jobs.map((job) => {
                    const isTriggering = triggering.has(job.id);
                    return (
                      <TableRow key={job.id}>
                        <TableCell className="max-w-[24rem] pl-4 whitespace-normal">
                          <div className="font-medium">{job.label}</div>
                          <div className="mt-1 line-clamp-2 text-xs text-muted-foreground">
                            {job.description}
                          </div>
                          <div className="mt-1 text-[11px] text-muted-foreground">
                            {job.schedule}
                          </div>
                        </TableCell>
                        <TableCell>
                          <Badge variant="secondary">{job.source}</Badge>
                        </TableCell>
                        <TableCell>
                          <JobStatusBadge job={job} />
                        </TableCell>
                        <TableCell>
                          <div className="text-xs">
                            {formatDateTime(job.last_run?.started_at ?? null)}
                          </div>
                          <div className="mt-1 text-[11px] text-muted-foreground">
                            {job.last_run
                              ? `${triggerLabel(job.last_run.trigger)} · ${formatDuration(job.last_run)}`
                              : "尚无运行记录"}
                          </div>
                          {job.last_run?.note && (
                            <div className="mt-1 max-w-52 truncate text-[11px] text-muted-foreground">
                              {job.last_run.note}
                            </div>
                          )}
                        </TableCell>
                        <TableCell className="text-xs text-muted-foreground">
                          {formatDateTime(job.next_run_at)}
                        </TableCell>
                        <TableCell className="pr-4 text-right">
                          <Button
                            size="sm"
                            variant="outline"
                            disabled={
                              !job.allow_manual ||
                              !syncToken ||
                              job.status === "running" ||
                              isTriggering
                            }
                            onClick={() => void manualSync(job)}
                          >
                            <ArrowsClockwiseIcon data-icon="inline-start" />
                            {job.status === "running"
                              ? "同步中"
                              : isTriggering
                                ? "启动中"
                                : "手动同步"}
                          </Button>
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="tables">
          <Card>
            <CardHeader>
              <CardTitle>PostgreSQL 数据表</CardTitle>
              <CardDescription>
                行数来自 PostgreSQL 统计信息，可能与精确 COUNT 有轻微延迟。
              </CardDescription>
            </CardHeader>
            <CardContent className="px-0">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="pl-4">表名</TableHead>
                    <TableHead className="text-right">估算行数</TableHead>
                    <TableHead className="pr-4 text-right">占用空间</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {snapshot.tables.length === 0 && (
                    <TableRow>
                      <TableCell colSpan={3}>
                        <EmptyState compact title="暂无数据表统计" />
                      </TableCell>
                    </TableRow>
                  )}
                  {snapshot.tables.map((table) => (
                    <TableRow key={table.name}>
                      <TableCell className="pl-4 font-mono text-xs">
                        {table.name}
                      </TableCell>
                      <TableCell className="text-right font-mono tabular-nums">
                        {formatNumber(table.row_count)}
                      </TableCell>
                      <TableCell className="pr-4 text-right font-mono tabular-nums text-muted-foreground">
                        {formatBytes(table.total_bytes)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
