"use client";

import { Line, LineChart, CartesianGrid, XAxis } from "recharts";
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart";
import { fmtMacroPct, fmtBigUSD } from "@/lib/format";
import { EmptyState } from "@/components/empty-state";

type FormatType = "pct" | "bigValue";

function getFormatter(type: FormatType): (v: number) => string {
  return type === "pct" ? fmtMacroPct : fmtBigUSD;
}

function fmtDate(dateStr: string | null | undefined): string {
  if (!dateStr) return "—";
  const d = new Date(dateStr);
  return d.toLocaleDateString("zh-CN", {
    year: "numeric",
    month: "2-digit",
  });
}

/**
 * 宏观指标走势图（shadcn charts LineChart）
 * 客户端组件：Recharts ResponsiveContainer 需要 DOM 测量。
 */
export function MacroTrendChart({
  data,
  color,
  formatType,
}: {
  data: { date: string; value: number }[];
  color: string;
  formatType: FormatType;
}) {
  if (data.length < 2) {
    return (
      <EmptyState compact title="无历史数据" className="h-32" />
    );
  }

  const formatValue = getFormatter(formatType);

  const chartConfig = {
    value: {
      label: "值",
      color,
    },
  } satisfies ChartConfig;

  return (
    <ChartContainer
      config={chartConfig}
      className="aspect-auto h-32 w-full"
    >
      <LineChart data={data}>
        <CartesianGrid vertical={false} strokeDasharray="3 3" />
        <XAxis
          dataKey="date"
          tickLine={false}
          axisLine={false}
          tickMargin={8}
          minTickGap={30}
          tickFormatter={(value) => fmtDate(value)}
        />
        <ChartTooltip
          cursor={false}
          content={
            <ChartTooltipContent
              labelFormatter={(value) => fmtDate(value as string)}
              formatter={(value) => (
                <div className="flex w-full flex-1 justify-between leading-none items-center">
                  <span className="text-muted-foreground">值</span>
                  <span className="font-mono font-medium text-foreground tabular-nums">
                    {formatValue(Number(value))}
                  </span>
                </div>
              )}
            />
          }
        />
        <Line
          dataKey="value"
          type="natural"
          stroke="var(--color-value)"
          strokeWidth={1.5}
          dot={false}
        />
      </LineChart>
    </ChartContainer>
  );
}
