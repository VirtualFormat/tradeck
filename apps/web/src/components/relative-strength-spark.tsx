"use client"

/**
 * 相对强弱比值 sparkline（隐轴迷你折线）
 * shadcn ChartContainer + Recharts LineChart
 */
import { Line, LineChart, XAxis, YAxis } from "recharts"

import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart"
import { EmptyState } from "@/components/empty-state"

const chartConfig = {
  ratio: {
    label: "比值",
    color: "var(--accent)",
  },
} satisfies ChartConfig

export function RelativeStrengthSpark({
  data,
}: {
  data: { date: string; ratio: number }[]
}) {
  if (data.length === 0) {
    return <EmptyState compact title="无数据" className="h-16 w-full" />
  }

  return (
    <ChartContainer config={chartConfig} className="aspect-auto h-16 w-full">
      <LineChart data={data} margin={{ top: 2, right: 0, bottom: 2, left: 0 }}>
        <XAxis dataKey="date" hide />
        <YAxis hide domain={["dataMin", "dataMax"]} />
        <ChartTooltip
          cursor={false}
          content={<ChartTooltipContent indicator="dot" />}
        />
        <Line
          type="monotone"
          dataKey="ratio"
          stroke="var(--color-ratio)"
          strokeWidth={1.5}
          dot={false}
          isAnimationActive={false}
        />
      </LineChart>
    </ChartContainer>
  )
}
