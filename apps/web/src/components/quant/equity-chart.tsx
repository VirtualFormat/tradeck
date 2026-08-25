"use client";

/**
 * 回测净值曲线：策略净值（实线）vs 基准（灰色虚线，无基准数据点则不画）
 * value / benchmark 均为归一化净值（起点 = 1）
 */
import { CartesianGrid, Line, LineChart, XAxis, YAxis } from "recharts";

import {
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart";

import type { EquityPoint } from "./types";

const chartConfig = {
  strategy: {
    label: "策略",
    color: "var(--chart-1)",
  },
  benchmark: {
    label: "基准",
    color: "var(--muted-foreground)",
  },
} satisfies ChartConfig;

export function EquityChart({ data }: { data: EquityPoint[] }) {
  // 基准可能为 null（降级）：没有任何有效基准点则不画基准线
  const hasBenchmark = data.some((p) => p.benchmark != null);
  const chartData = data.map((p) => ({
    date: p.date,
    strategy: p.value,
    benchmark: p.benchmark,
  }));

  return (
    <ChartContainer
      config={chartConfig}
      className="aspect-auto h-[280px] w-full"
    >
      <LineChart data={chartData} margin={{ top: 4, right: 8, bottom: 0, left: 8 }}>
        <CartesianGrid vertical={false} />
        <XAxis
          dataKey="date"
          tickLine={false}
          axisLine={false}
          tickMargin={8}
          minTickGap={48}
          tickFormatter={(v: string) => v.slice(5)}
        />
        <YAxis
          tickLine={false}
          axisLine={false}
          tickMargin={8}
          width={48}
          domain={["auto", "auto"]}
          tickFormatter={(v: number) => v.toFixed(3)}
        />
        <ChartTooltip
          content={
            <ChartTooltipContent
              indicator="dot"
              formatter={(value) =>
                typeof value === "number" ? value.toFixed(4) : value
              }
            />
          }
        />
        <ChartLegend content={<ChartLegendContent />} />
        <Line
          type="monotone"
          dataKey="strategy"
          stroke="var(--color-strategy)"
          strokeWidth={2}
          dot={false}
          isAnimationActive={false}
        />
        {hasBenchmark && (
          <Line
            type="monotone"
            dataKey="benchmark"
            stroke="var(--color-benchmark)"
            strokeWidth={1.5}
            strokeDasharray="5 3"
            dot={false}
            isAnimationActive={false}
          />
        )}
      </LineChart>
    </ChartContainer>
  );
}
