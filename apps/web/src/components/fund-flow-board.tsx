/**
 * 资金流向榜（服务端组件，shadcn Bar Chart - Custom Label 样式）
 * - 数据：backend /api/fundflow
 * - 左：资金流入红榜 Top 10（红柱，主力净额）；右：资金流出绿榜 Top 10（绿柱）
 */
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { FundFlowBarChart, type FlowBarRow } from "@/components/fund-flow-bar-chart";
import { EmptyState } from "@/components/empty-state";
import { fmtDataTime } from "@/lib/format";

interface FundFlowItem {
  symbol: string;
  name: string | null;
  price: number | null;
  change_percent: number | null;
  turnover_rate: number | null;
  net_amount: number | null;
  /** 榜单更新时间（fund_flow.updated_at，5 分钟级即时榜） */
  updated_at?: string | null;
}

async function fetchFundFlow(
  direction: "in" | "out",
  date?: string
): Promise<FundFlowItem[]> {
  const BACKEND_API_URL =
    process.env.BACKEND_API_URL ?? "http://localhost:8080";
  try {
    const dateQuery = date ? `&date=${date}` : "";
    const res = await fetch(
      `${BACKEND_API_URL}/api/fundflow?direction=${direction}&limit=10${dateQuery}`,
      { headers: { Accept: "application/json" } }
    );
    if (!res.ok) return [];
    const data = await res.json();
    return Array.isArray(data) ? data : [];
  } catch {
    return [];
  }
}

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

export async function FundFlowBoard({ date }: { date?: string }) {
  const [inflow, outflow] = await Promise.all([
    fetchFundFlow("in", date),
    fetchFundFlow("out", date),
  ]);

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
