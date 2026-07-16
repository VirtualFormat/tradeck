"use client"

import { Bar, BarChart, CartesianGrid, Cell, XAxis, YAxis } from "recharts"

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart"

interface MoverItem {
  symbol: string
  percent_change: number | null
}

interface MoversBarChartProps {
  gainers: MoverItem[]
  losers: MoverItem[]
}

const chartConfig = {
  changePct: {
    label: "涨跌幅",
  },
  gainer: {
    label: "Gainers",
    color: "var(--down)",
  },
  loser: {
    label: "Losers",
    color: "var(--up)",
  },
} satisfies ChartConfig

export function MoversBarChart({ gainers, losers }: MoversBarChartProps) {
  const data = [
    ...gainers.slice(0, 5).map((item) => ({
      symbol: item.symbol,
      changePct: (item.percent_change ?? 0) * 100,
      kind: "gainer" as const,
      fill: "var(--color-gainer)",
    })),
    ...losers.slice(0, 5).map((item) => ({
      symbol: item.symbol,
      changePct: (item.percent_change ?? 0) * 100,
      kind: "loser" as const,
      fill: "var(--color-loser)",
    })),
  ].sort((a, b) => b.changePct - a.changePct)

  if (data.length === 0) {
    return null
  }

  const maxAbs = Math.max(...data.map((d) => Math.abs(d.changePct)), 0) * 1.1

  return (
    <Card
      size="sm"
      className="@container/card bg-linear-to-t from-primary/5 to-card shadow-xs dark:bg-card"
    >
      <CardHeader>
        <CardTitle className="text-base font-medium text-fg-dim">
          涨跌可视化
        </CardTitle>
        <CardDescription>
          <span className="hidden @[540px]/card:block">
            Top 5 涨幅 / Top 5 跌幅
          </span>
          <span className="@[540px]/card:hidden">Top 5 涨跌</span>
        </CardDescription>
      </CardHeader>
      <CardContent className="px-2 pt-4 sm:px-6 sm:pt-6">
        <ChartContainer
          config={chartConfig}
          className="aspect-auto h-[300px] w-full"
        >
          <BarChart
            data={data}
            layout="vertical"
            margin={{ left: 8, right: 16 }}
          >
            <CartesianGrid horizontal={false} />
            <XAxis
              type="number"
              domain={[-maxAbs, maxAbs]}
              tickLine={false}
              axisLine={false}
              tickMargin={8}
              tickFormatter={(value: number) => `${value.toFixed(1)}%`}
            />
            <YAxis
              dataKey="symbol"
              type="category"
              tickLine={false}
              axisLine={false}
              tickMargin={8}
              width={88}
            />
            <ChartTooltip
              cursor={false}
              content={
                <ChartTooltipContent
                  formatter={(value) => {
                    const num =
                      typeof value === "number" ? value : Number(value)
                    return (
                      <div className="flex w-full flex-1 justify-between leading-none items-center">
                        <span className="text-muted-foreground">涨跌幅</span>
                        <span className="font-mono font-medium text-foreground tabular-nums">
                          {Number.isFinite(num)
                            ? `${num.toFixed(2)}%`
                            : String(value)}
                        </span>
                      </div>
                    )
                  }}
                />
              }
            />
            <Bar dataKey="changePct" radius={4}>
              {data.map((entry) => (
                <Cell key={entry.symbol} fill={entry.fill} />
              ))}
            </Bar>
          </BarChart>
        </ChartContainer>
      </CardContent>
    </Card>
  )
}
