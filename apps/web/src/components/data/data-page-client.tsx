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
  WarningIcon,
} from "@phosphor-icons/react";

import {
  type DataHealthStatus,
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

/** 数据质量度量（data-api /api/system/quality） */
interface QualityMetric {
  table_name: string;
  date: string | null;
  total: number;
  accepted: number;
  rejected: number;
  repaired: number;
  quality_score: number | null;
  updated_at: string | null;
}

interface QualityReject {
  source_table: string;
  symbol: string | null;
  reject_reason: string | null;
  severity: string | null;
  rejected_at: string | null;
}

interface QualitySnapshot {
  metrics: QualityMetric[];
  recent_rejects: QualityReject[];
}

const EMPTY_SNAPSHOT: DataSystemSnapshot = {
  jobs: [],
  tables: [],
  daily_markets: [],
  summary: {
    job_count: 0,
    running_count: 0,
    error_count: 0,
    empty_count: 0,
    partial_count: 0,
    stale_count: 0,
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

function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!match) return value;
  return `${match[1]}-${match[2]}-${match[3]}`;
}

function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(date);
}

function formatDataCutoff(
  dateValue: string | null | undefined,
  dateTimeValue: string | null | undefined
): string {
  if (dateValue) return formatDate(dateValue);
  return formatDateTime(dateTimeValue);
}

function formatCompactDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
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

function DataHealthBadge({
  status,
}: {
  status: DataHealthStatus | null | undefined;
}) {
  if (status === "fresh") {
    return (
      <Badge variant="outline">
        <CheckCircleIcon data-icon="inline-start" className="text-down" />
        正常
      </Badge>
    );
  }
  if (status === "partial") {
    return (
      <Badge variant="outline" className="border-warn/40 text-warn">
        <WarningIcon data-icon="inline-start" />
        部分数据
      </Badge>
    );
  }
  if (status === "empty") {
    return (
      <Badge variant="outline" className="border-warn/40 text-warn">
        <DatabaseIcon data-icon="inline-start" />
        空结果
      </Badge>
    );
  }
  if (status === "stale") {
    return (
      <Badge variant="outline" className="border-warn/40 text-warn">
        <ClockCountdownIcon data-icon="inline-start" />
        陈旧
      </Badge>
    );
  }
  if (status === "unknown") {
    return <Badge variant="outline">待判断</Badge>;
  }
  return <Badge variant="outline">待判断</Badge>;
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
  if (job.status === "done") {
    if (job.data_health.status === "fresh") {
      return <DataHealthBadge status="fresh" />;
    }
    if (job.data_health.status === "unknown") {
      return (
        <Badge variant="outline">
          <CheckCircleIcon data-icon="inline-start" />
          已完成
        </Badge>
      );
    }
    return <DataHealthBadge status={job.data_health.status} />;
  }
  if (job.status === "error") {
    return (
      <Badge variant="destructive">
        <WarningCircleIcon data-icon="inline-start" />
        异常
      </Badge>
    );
  }
  if (job.status === "idle") {
    return <Badge variant="outline">等待运行</Badge>;
  }
  return <DataHealthBadge status={job.status} />;
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
  const names: Record<"CN" | "HK" | "US", string> = {
    CN: "A 股",
    HK: "港股",
    US: "美股",
  };
  const dailyTable = snapshot.tables.find(
    (item) => item.name === "daily_prices"
  );

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        <span>daily_prices 全表状态</span>
        <DataHealthBadge status={dailyTable?.freshness} />
        {dailyTable?.freshness_note && <span>{dailyTable.freshness_note}</span>}
      </div>
      <div className="grid gap-3 md:grid-cols-3">
        {(["CN", "HK", "US"] as const).map((market) => {
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
                  最新交易日 {formatDate(stat?.latest_date)}
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

/** 质量分展示：null → 灰色「—」；>= 0.99 绿、0.9-0.99 黄、< 0.9 红（百分比，1 位小数） */
function QualityScoreValue({ score }: { score: number | null }) {
  if (score === null || Number.isNaN(score)) {
    return <span className="text-muted-foreground">—</span>;
  }
  const pct = score * 100;
  const colorClass =
    score >= 0.99 ? "text-down" : score >= 0.9 ? "text-warn" : "text-up";
  return (
    <span className={cn("font-mono font-semibold tabular-nums", colorClass)}>
      {pct.toFixed(1)}%
    </span>
  );
}

/** 拦截样本 severity 徽标：P0/P1 红、P2 黄（可疑但已放行），其余灰 */
function SeverityBadge({ severity }: { severity: string | null }) {
  if (severity === "P0" || severity === "P1") {
    return <Badge variant="destructive">{severity} 已拦截</Badge>;
  }
  if (severity === "P2") {
    return (
      <Badge variant="outline" className="border-warn/40 text-warn">
        P2 可疑但已放行
      </Badge>
    );
  }
  return <Badge variant="outline">{severity ?? "未知"}</Badge>;
}

/** 数据质量面板：质量分概览 + 近 N 天同步状态 + 拦截样本 */
function QualityPanel({ snapshot }: { snapshot: QualitySnapshot }) {
  const { metrics, recent_rejects } = snapshot;

  // 质量分概览：每表取最新一天的 quality_score
  const latestByTable = useMemo(() => {
    const map = new Map<string, QualityMetric>();
    for (const metric of metrics) {
      const prev = map.get(metric.table_name);
      if (!prev || (metric.date ?? "") > (prev.date ?? "")) {
        map.set(metric.table_name, metric);
      }
    }
    return [...map.values()].sort((a, b) =>
      a.table_name.localeCompare(b.table_name)
    );
  }, [metrics]);

  // 同步状态：近 N 天按表聚合 total/accepted/rejected/repaired
  const totalsByTable = useMemo(() => {
    const map = new Map<
      string,
      { total: number; accepted: number; rejected: number; repaired: number }
    >();
    for (const metric of metrics) {
      const agg = map.get(metric.table_name) ?? {
        total: 0,
        accepted: 0,
        rejected: 0,
        repaired: 0,
      };
      agg.total += metric.total;
      agg.accepted += metric.accepted;
      agg.rejected += metric.rejected;
      agg.repaired += metric.repaired;
      map.set(metric.table_name, agg);
    }
    return [...map.entries()]
      .map(([table_name, agg]) => ({ table_name, ...agg }))
      .sort((a, b) => a.table_name.localeCompare(b.table_name));
  }, [metrics]);

  if (metrics.length === 0 && recent_rejects.length === 0) {
    return (
      <Card>
        <CardContent>
          <EmptyState
            title="暂无数据质量记录"
            description="collector 数据质量层尚未写库；当日任务跑完后此处会展示质量分与拦截样本。"
          />
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-6">
      <section className="space-y-3">
        <div>
          <h3 className="text-sm font-medium">质量分概览</h3>
          <p className="mt-1 text-xs text-muted-foreground">
            每张表最近一天的入库质量分（合格数 ÷ 总数，修复后的记录计为合格）。
          </p>
        </div>
        {latestByTable.length === 0 ? (
          <Card>
            <CardContent>
              <EmptyState compact title="暂无质量分记录" />
            </CardContent>
          </Card>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {latestByTable.map((metric) => (
              <Card key={metric.table_name} size="sm">
                <CardHeader>
                  <CardTitle className="font-mono text-xs">
                    {metric.table_name}
                  </CardTitle>
                  <CardAction>
                    <Badge variant="outline">
                      {formatDate(metric.date)}
                    </Badge>
                  </CardAction>
                </CardHeader>
                <CardContent>
                  <div className="text-xl">
                    <QualityScoreValue score={metric.quality_score} />
                  </div>
                  <div className="mt-1 text-xs text-muted-foreground">
                    当日 {formatNumber(metric.total)} 条 · 拦截{" "}
                    {formatNumber(metric.rejected)} · 修复{" "}
                    {formatNumber(metric.repaired)}
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        )}
      </section>

      <section className="space-y-3">
        <div>
          <h3 className="text-sm font-medium">同步状态概览</h3>
          <p className="mt-1 text-xs text-muted-foreground">
            近 N 天各表入库条数聚合：总数 / 合格 / 拦截 / 修复。
          </p>
        </div>
        <Card>
          <CardContent className="px-0">
            <Table className="min-w-[640px]">
              <TableHeader>
                <TableRow>
                  <TableHead className="pl-4">表名</TableHead>
                  <TableHead className="text-right">总数</TableHead>
                  <TableHead className="text-right">合格</TableHead>
                  <TableHead className="text-right">拦截</TableHead>
                  <TableHead className="pr-4 text-right">修复</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {totalsByTable.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={5}>
                      <EmptyState compact title="暂无同步质量记录" />
                    </TableCell>
                  </TableRow>
                )}
                {totalsByTable.map((row) => (
                  <TableRow key={row.table_name}>
                    <TableCell className="pl-4 font-mono text-xs">
                      {row.table_name}
                    </TableCell>
                    <TableCell className="text-right font-mono tabular-nums">
                      {formatNumber(row.total)}
                    </TableCell>
                    <TableCell className="text-right font-mono tabular-nums text-down">
                      {formatNumber(row.accepted)}
                    </TableCell>
                    <TableCell
                      className={cn(
                        "text-right font-mono tabular-nums",
                        row.rejected > 0
                          ? "text-up"
                          : "text-muted-foreground"
                      )}
                    >
                      {formatNumber(row.rejected)}
                    </TableCell>
                    <TableCell
                      className={cn(
                        "pr-4 text-right font-mono tabular-nums",
                        row.repaired > 0
                          ? "text-warn"
                          : "text-muted-foreground"
                      )}
                    >
                      {formatNumber(row.repaired)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      </section>

      <section className="space-y-3">
        <div>
          <h3 className="text-sm font-medium">拦截样本</h3>
          <p className="mt-1 text-xs text-muted-foreground">
            最近被质量层拦下或标记的记录（最多 100 条）；P2 为可疑但已放行。
          </p>
        </div>
        <Card>
          <CardContent className="px-0">
            <Table className="min-w-[720px]">
              <TableHeader>
                <TableRow>
                  <TableHead className="pl-4">级别</TableHead>
                  <TableHead>表名</TableHead>
                  <TableHead>标的</TableHead>
                  <TableHead>原因</TableHead>
                  <TableHead className="pr-4 text-right">时间</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {recent_rejects.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={5}>
                      <EmptyState
                        compact
                        title="暂无拦截样本"
                        description="最近没有记录被质量层拦截或标记。"
                      />
                    </TableCell>
                  </TableRow>
                )}
                {recent_rejects.map((reject, index) => (
                  <TableRow
                    key={`${reject.source_table}-${reject.symbol}-${reject.rejected_at}-${index}`}
                  >
                    <TableCell className="pl-4">
                      <SeverityBadge severity={reject.severity} />
                    </TableCell>
                    <TableCell className="font-mono text-xs">
                      {reject.source_table}
                    </TableCell>
                    <TableCell className="font-mono text-xs">
                      {reject.symbol ?? "—"}
                    </TableCell>
                    <TableCell className="max-w-80 whitespace-normal text-xs text-muted-foreground">
                      {reject.reject_reason ?? "—"}
                    </TableCell>
                    <TableCell className="pr-4 text-right text-xs text-muted-foreground">
                      {formatCompactDateTime(reject.rejected_at)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      </section>
    </div>
  );
}

export function DataPageClient() {
  const [snapshot, setSnapshot] =
    useState<DataSystemSnapshot>(EMPTY_SNAPSHOT);
  const [quality, setQuality] = useState<QualitySnapshot>({
    metrics: [],
    recent_rejects: [],
  });
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

  // 质量度量独立低频轮询（30s）：质量接口查两张表（近 7 天 metrics 全量 +
  // rejects LIMIT 100），不随主快照的 3s 高频轮询；失败保留旧数据 + console 留痕。
  const refreshQuality = useCallback(async () => {
    try {
      const res = await fetch("/api/system/quality?days=7", { cache: "no-store" });
      if (!res.ok) throw new Error(`质量度量接口 ${res.status}`);
      setQuality((await res.json()) as QualitySnapshot);
    } catch (error) {
      // 保留旧数据不清空，但留痕便于发现停更（与主快照 loadError 分开展示）
      console.warn("数据质量度量刷新失败：", error);
    }
  }, []);

  useEffect(() => {
    // 首调用 setTimeout 推迟（避免 effect 内同步 setState，与主 refresh 的 initialTimer 一致）
    const initialTimer = window.setTimeout(() => void refreshQuality(), 0);
    const timer = window.setInterval(() => void refreshQuality(), 30_000);
    return () => {
      window.clearTimeout(initialTimer);
      window.clearInterval(timer);
    };
  }, [refreshQuality]);

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
          description={`${snapshot.summary.running_count} 运行中 · ${snapshot.summary.error_count} 异常 · ${snapshot.summary.partial_count ?? 0} 部分 · ${snapshot.summary.empty_count ?? 0} 空结果 · ${snapshot.summary.stale_count ?? 0} 陈旧`}
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
          <TabsTrigger value="quality">数据质量</TabsTrigger>
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
              <Table className="min-w-[980px]">
                <TableHeader>
                  <TableRow>
                    <TableHead className="pl-4">任务</TableHead>
                    <TableHead>数据源</TableHead>
                    <TableHead>状态</TableHead>
                    <TableHead>数据截止</TableHead>
                    <TableHead>最近运行</TableHead>
                    <TableHead>下次调度</TableHead>
                    <TableHead className="text-right pr-4">操作</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {snapshot.jobs.length === 0 && (
                    <TableRow>
                      <TableCell colSpan={7}>
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
                        <TableCell className="max-w-60 whitespace-normal">
                          <div className="text-xs">
                            {formatDataCutoff(
                              job.data_health?.latest_data_date,
                              job.data_health?.latest_data_at
                            )}
                          </div>
                          {job.data_health?.note && (
                            <div
                              className={cn(
                                "mt-1 text-[11px] leading-4",
                                job.data_health?.status === "stale" ||
                                  job.data_health?.status === "partial" ||
                                  job.data_health?.status === "empty"
                                  ? "text-warn"
                                  : "text-muted-foreground"
                              )}
                            >
                              {job.data_health.note}
                            </div>
                          )}
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
              <Table className="min-w-[760px]">
                <TableHeader>
                  <TableRow>
                    <TableHead className="pl-4">表名</TableHead>
                    <TableHead className="text-right">估算行数</TableHead>
                    <TableHead>最新数据</TableHead>
                    <TableHead>健康状态</TableHead>
                    <TableHead className="pr-4 text-right">占用空间</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {snapshot.tables.length === 0 && (
                    <TableRow>
                      <TableCell colSpan={5}>
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
                      <TableCell className="text-xs">
                        {formatDataCutoff(
                          table.latest_data_date,
                          table.latest_data_at
                        )}
                      </TableCell>
                      <TableCell className="max-w-64 whitespace-normal">
                        <DataHealthBadge status={table.freshness} />
                        {table.freshness_note && (
                          <div
                            className={cn(
                              "mt-1 text-[11px] leading-4",
                              table.freshness === "stale" ||
                                table.freshness === "partial" ||
                                table.freshness === "empty"
                                ? "text-warn"
                                : "text-muted-foreground"
                            )}
                          >
                            {table.freshness_note}
                          </div>
                        )}
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

        <TabsContent value="quality">
          <QualityPanel snapshot={quality} />
        </TabsContent>
      </Tabs>
    </div>
  );
}
