/**
 * 资金流向榜（服务端组件，shadcn Bar Chart - Custom Label 样式）
 * - 数据：backend /api/fundflow
 * - 左：资金流入红榜 Top 10（红柱，主力净额）；右：资金流出绿榜 Top 10（绿柱）
 */
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  FundFlowBarChart,
  type FlowBarRow,
} from "@/components/fund-flow-bar-chart";
import { EmptyState } from "@/components/empty-state";
import { fmtDataTime } from "@/lib/format";
import { fetchFundFlow, type FundFlowItem } from "@/lib/openbb";

function toRows(items: FundFlowItem[]): FlowBarRow[] {
  return items
    .filter((i) => i.net_amount != null)
    .map((i) => ({
      name: i.name ?? i.symbol,
      net: i.net_amount as number,
      size: Math.abs(i.net_amount as number),
      changePercent: i.change_percent,
      turnoverRate: i.turnover_rate,
    }));
}

function DashboardFlowColumn({
  title,
  rows,
  variant,
}: {
  title: string;
  rows: FlowBarRow[];
  variant: "in" | "out";
}) {
  const colorClass = variant === "in" ? "text-up" : "text-down";

  return (
    <div className="min-w-0">
      <p className={`mb-0.5 text-[11px] font-medium ${colorClass}`}>{title}</p>
      {rows.length > 0 ? (
        <FundFlowBarChart rows={rows.slice(0, 5)} variant={variant} compact />
      ) : (
        <EmptyState
          compact
          title={variant === "in" ? "等待流入数据" : "等待流出数据"}
          className="h-[120px]"
        />
      )}
    </div>
  );
}

function DashboardFundFlow({
  inflow,
  outflow,
  date,
}: {
  inflow: FundFlowItem[];
  outflow: FundFlowItem[];
  date?: string;
}) {
  const latestUpdatedAt = inflow[0]?.updated_at ?? outflow[0]?.updated_at;
  const snapshotDate =
    inflow[0]?.snapshot_date ?? outflow[0]?.snapshot_date ?? date;
  const dateMatch = snapshotDate?.match(/^\d{4}-(\d{2})-(\d{2})/);
  const today = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
  const currentTime = latestUpdatedAt
    ? new Intl.DateTimeFormat("zh-CN", {
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
        timeZone: "Asia/Shanghai",
      }).format(new Date(latestUpdatedAt))
    : null;
  const dateLabel = dateMatch ? `${dateMatch[1]}-${dateMatch[2]}` : null;
  const isLatestToday = snapshotDate === today;
  const timeLabel = [dateLabel, isLatestToday ? currentTime : null]
    .filter(Boolean)
    .join(" · ");
  const freshnessLabel = date
    ? "日快照"
    : isLatestToday
      ? "5分钟"
      : "最近快照";

  return (
    <Card size="sm" className="gap-2 py-3 sm:h-[185px]">
      <CardHeader className="px-3">
        <CardTitle className="text-xs font-semibold text-fg-dim">
          主力资金 红绿榜&nbsp; A股
        </CardTitle>
        <CardAction className="text-[10px] text-muted-foreground tabular-nums">
          {timeLabel ? `${timeLabel} · ` : ""}
          {freshnessLabel}
        </CardAction>
      </CardHeader>
      <CardContent className="grid min-h-0 flex-1 grid-cols-1 gap-3 px-3 sm:grid-cols-2 sm:gap-6">
        <DashboardFlowColumn
          title="净流入 Top"
          rows={toRows(inflow)}
          variant="in"
        />
        <DashboardFlowColumn
          title="净流出 Top"
          rows={toRows(outflow)}
          variant="out"
        />
      </CardContent>
    </Card>
  );
}

function FlowCard({
  title,
  rows,
  colorClass,
  variant,
  timeLabel,
}: {
  title: string;
  rows: FlowBarRow[];
  colorClass: string;
  variant: "in" | "out";
  timeLabel?: string | null;
}) {
  return (
    <Card
      size="sm"
      className="@container/card bg-linear-to-t from-primary/5 to-card shadow-xs dark:bg-card"
    >
      <CardHeader>
        <CardTitle className={`text-base font-medium ${colorClass}`}>
          {title}
        </CardTitle>
        {timeLabel && (
          <CardDescription className="text-xs text-muted-foreground">
            {timeLabel}
          </CardDescription>
        )}
      </CardHeader>
      <CardContent>
        {rows.length > 0 ? (
          <FundFlowBarChart rows={rows} variant={variant} />
        ) : (
          <EmptyState compact title="无数据" />
        )}
      </CardContent>
    </Card>
  );
}

export async function FundFlowBoard({
  date,
  variant = "default",
}: {
  date?: string;
  variant?: "default" | "dashboard";
}) {
  const limit = variant === "dashboard" ? 5 : 10;
  const [inflow, outflow] = await Promise.all([
    fetchFundFlow("in", date, limit),
    fetchFundFlow("out", date, limit),
  ]);

  if (variant === "dashboard") {
    return <DashboardFundFlow inflow={inflow} outflow={outflow} date={date} />;
  }

  // 即时榜（5 分钟级）：用榜单首行的 updated_at 显时分
  const inTime = fmtDataTime(inflow[0]?.updated_at);
  const outTime = fmtDataTime(outflow[0]?.updated_at);

  return (
    <>
      <FlowCard
        title="资金流入红榜 Top 10"
        rows={toRows(inflow)}
        colorClass="text-up"
        variant="in"
        timeLabel={inTime}
      />
      <FlowCard
        title="资金流出绿榜 Top 10"
        rows={toRows(outflow)}
        colorClass="text-down"
        variant="out"
        timeLabel={outTime}
      />
    </>
  );
}
