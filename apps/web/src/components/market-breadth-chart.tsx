"use client"

/**
 * 市场宽度趋势图（近 60 日上涨/下跌家数面积图）
 * shadcn ChartContainer + Recharts AreaChart：红涨绿跌（上涨=var(--up)，下跌=var(--down)）
 */
import { Area, AreaChart, CartesianGrid, XAxis, YAxis } from "recharts"

import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  ChartLegend,
  ChartLegendContent,
  type ChartConfig,
} from "@/components/ui/chart"
import { EmptyState } from "@/components/empty-state"

export interface BreadthTrendPoint {
  date: string
  up: number | null
  down: number | null
}

const chartConfig = {
  up: {
    label: "上涨家数",
    color: "var(--up)",
  },
  down: {
    label: "下跌家数",
    color: "var(--down)",
  },
} satisfies ChartConfig

export function MarketBreadthChart({ data }: { data: BreadthTrendPoint[] }) {
  if (data.length === 0) {
    return (
      <EmptyState compact title="无数据" className="h-[260px] w-full" />
    )
  }

  return (
    <ChartContainer config={chartConfig} className="aspect-auto h-[260px] w-full">
      <AreaChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 8 }}>
        <defs>
          <linearGradient id="breadth-up" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor="var(--color-up)" stopOpacity={0.4} />
            <stop offset="95%" stopColor="var(--color-up)" stopOpacity={0.05} />
          </linearGradient>
          <linearGradient id="breadth-down" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor="var(--color-down)" stopOpacity={0.4} />
            <stop offset="95%" stopColor="var(--color-down)" stopOpacity={0.05} />
          </linearGradient>
        </defs>
        <CartesianGrid vertical={false} />
        <XAxis
          dataKey="date"
          tickLine={false}
          axisLine={false}
          tickMargin={8}
          minTickGap={32}
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
          domain={[0, "dataMax"]}
        />
        <ChartTooltip
          cursor={false}
          content={<ChartTooltipContent indicator="dot" />}
        />
        <ChartLegend content={<ChartLegendContent />} />
        <Area
          type="monotone"
          dataKey="up"
          stroke="var(--color-up)"
          fill="url(#breadth-up)"
          strokeWidth={1.5}
          dot={false}
          isAnimationActive={false}
        />
        <Area
          type="monotone"
          dataKey="down"
          stroke="var(--color-down)"
          fill="url(#breadth-down)"
          strokeWidth={1.5}
          dot={false}
          isAnimationActive={false}
        />
      </AreaChart>
    </ChartContainer>
  )
}
