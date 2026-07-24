"use client"

/**
 * 美债收益率曲线图（最新 / 1 月前 / 1 年前 三条线）
 * shadcn ChartContainer + Recharts LineChart
 */
import { Line, LineChart, CartesianGrid, XAxis, YAxis } from "recharts"

import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  ChartLegend,
  ChartLegendContent,
  type ChartConfig,
} from "@/components/ui/chart"
import { EmptyState } from "@/components/empty-state"
import type { YieldCurvePoint } from "@/lib/openbb"

const chartConfig = {
  latest: {
    label: "最新",
    color: "var(--accent)",
  },
  ago_1m: {
    label: "1月前",
    color: "var(--muted)",
  },
  ago_1y: {
    label: "1年前",
    color: "var(--muted)",
  },
} satisfies ChartConfig

export function YieldCurveChart({ data }: { data: YieldCurvePoint[] }) {
  if (data.length === 0) {
    return (
      <EmptyState compact title="无数据" className="h-[260px] w-full" />
    )
  }

  return (
    <ChartContainer config={chartConfig} className="aspect-auto h-[260px] w-full">
      <LineChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 8 }}>
        <CartesianGrid vertical={false} />
        <XAxis dataKey="tenor" tickLine={false} axisLine={false} tickMargin={8} />
        <YAxis
          tickLine={false}
          axisLine={false}
          tickMargin={8}
          width={40}
          domain={["dataMin - 0.2", "dataMax + 0.2"]}
          tickFormatter={(v: number) => v.toFixed(1)}
        />
        <ChartTooltip
          cursor={false}
          content={<ChartTooltipContent indicator="dot" />}
        />
        <ChartLegend content={<ChartLegendContent />} />
        <Line
          type="monotone"
          dataKey="latest"
          stroke="var(--color-latest)"
          strokeWidth={2}
          dot={{ r: 2.5 }}
          isAnimationActive={false}
        />
        <Line
          type="monotone"
          dataKey="ago_1m"
          stroke="var(--color-ago_1m)"
          strokeWidth={1.5}
          dot={false}
          isAnimationActive={false}
        />
        <Line
          type="monotone"
          dataKey="ago_1y"
          stroke="var(--color-ago_1y)"
          strokeWidth={1.5}
          strokeDasharray="4 4"
          dot={false}
          isAnimationActive={false}
        />
      </LineChart>
    </ChartContainer>
  )
}
