"use client";

import * as React from "react";
import { Cell, Pie, PieChart } from "recharts";

import {
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart";

export interface MarketPieDatum {
  name: string;
  value: number;
}

const CHART_COLORS = [
  "var(--chart-1)",
  "var(--chart-2)",
  "var(--chart-3)",
  "var(--chart-4)",
  "var(--chart-5)",
] as const;

/**
 * 市场占比饼图（shadcn charts PieChart）
 * 客户端组件：Recharts ResponsiveContainer 需要 DOM 测量。
 */
export function MarketPieChart({ data }: { data: MarketPieDatum[] }) {
  const total = React.useMemo(
    () => data.reduce((sum, d) => sum + (d.value ?? 0), 0),
    [data]
  );

  if (!data.length || total <= 0) {
    return (
      <div className="flex h-[220px] items-center justify-center text-xs text-muted">
        暂无分布数据
      </div>
    );
  }

  const chartData = data.map((d, i) => ({
    name: d.name,
    value: d.value,
    fill: CHART_COLORS[i % CHART_COLORS.length],
  }));

  const chartConfig = chartData.reduce<ChartConfig>((acc, d) => {
    acc[d.name] = {
      label: d.name,
      color: d.fill,
    };
    return acc;
  }, {});

  return (
    <ChartContainer
      config={chartConfig}
      className="mx-auto aspect-square max-h-[220px]"
    >
      <PieChart>
        <ChartTooltip
          content={
            <ChartTooltipContent
              nameKey="value"
              hideLabel
              formatter={(value, name) => {
                const v = Number(value);
                const pct = total > 0 ? ((v / total) * 100).toFixed(1) : "0.0";
                return (
                  <div className="flex w-full flex-1 justify-between leading-none items-center gap-3">
                    <span className="text-muted-foreground">{name}</span>
                    <span className="font-mono font-medium text-foreground tabular-nums">
                      {v.toLocaleString()} ({pct}%)
                    </span>
                  </div>
                );
              }}
            />
          }
        />
        <Pie
          data={chartData}
          dataKey="value"
          nameKey="name"
          innerRadius={50}
          strokeWidth={2}
        >
          {chartData.map((d) => (
            <Cell key={d.name} fill={d.fill} />
          ))}
        </Pie>
        <ChartLegend content={<ChartLegendContent nameKey="name" />} />
      </PieChart>
    </ChartContainer>
  );
}
