"use client"

/**
 * 10Y-2Y 利差面积图（bp，零轴参考线）
 * shadcn ChartContainer + Recharts AreaChart
 */
import { Area, AreaChart, CartesianGrid, ReferenceLine, XAxis, YAxis } from "recharts"

import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart"
import { EmptyState } from "@/components/empty-state"
import type { YieldSpreadPoint } from "@/lib/openbb"

const chartConfig = {
  spread_bp: {
    label: "10Y-2Y 利差 (bp)",
    color: "var(--accent)",
  },
} satisfies ChartConfig

export function YieldSpreadChart({ data }: { data: YieldSpreadPoint[] }) {
  if (data.length === 0) {
    return (
      <EmptyState compact title="无数据" className="h-[200px] w-full" />
    )
  }

  return (
    <ChartContainer config={chartConfig} className="aspect-auto h-[200px] w-full">
      <AreaChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 8 }}>
        <defs>
          <linearGradient id="yield-spread" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor="var(--color-spread_bp)" stopOpacity={0.4} />
            <stop offset="95%" stopColor="var(--color-spread_bp)" stopOpacity={0.05} />
          </linearGradient>
        </defs>
        <CartesianGrid vertical={false} />
        <XAxis
          dataKey="date"
          tickLine={false}
          axisLine={false}
          tickMargin={8}
          minTickGap={48}
          tickFormatter={(value: string) => {
            // YYYY-MM-DD → M/D
            const d = new Date(value)
            return `${d.getMonth() + 1}/${d.getDate()}`
          }}
        />
        <YAxis
          tickLine={false}
          axisLine={false}
          tickMargin={8}
          width={48}
          tickFormatter={(v: number) => v.toFixed(0)}
        />
        <ReferenceLine y={0} stroke="var(--muted)" strokeDasharray="4 4" />
        <ChartTooltip
          cursor={false}
          content={<ChartTooltipContent indicator="dot" />}
        />
        <Area
          type="monotone"
          dataKey="spread_bp"
          stroke="var(--color-spread_bp)"
          fill="url(#yield-spread)"
          strokeWidth={1.5}
          dot={false}
          isAnimationActive={false}
        />
      </AreaChart>
    </ChartContainer>
  )
}
