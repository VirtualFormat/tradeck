/**
 * 宏观指标卡片（shadcn Card + mini AreaChart）
 * - mini AreaChart 显示历史序列相对首值的累计涨跌幅
 * - hover 显示日期 + 涨跌幅%
 * - 右上角 Badge 显示环比变化
 * - tradeck 主题：红涨绿跌 text-up / text-down；无方向用 var(--muted-foreground)
 */
"use client"

import { useMemo } from "react"
import Link from "next/link"
import { Area, AreaChart, XAxis } from "recharts"
import { TrendUpIcon, TrendDownIcon } from "@phosphor-icons/react"
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart"

export interface MacroCardProps {
  label: string
  value: string
  change: string | null
  date: string
  href: string
  /** 历史序列（旧 → 新），用于 mini 走势 */
  hist?: { date: string; value: number }[]
}

export function MacroCard({ label, value, change, date, href, hist }: MacroCardProps) {
  const isUp = change ? change.startsWith("+") : false
  const isDown = change ? change.startsWith("-") : false
  const TrendIcon = isUp ? TrendUpIcon : isDown ? TrendDownIcon : null
  const trendColor = isUp ? "text-up" : isDown ? "text-down" : ""
  const lineColor = isUp ? "var(--up)" : isDown ? "var(--down)" : "var(--muted-foreground)"
  const gradientId = `fill-macro-${label.replace(/[^a-zA-Z0-9]/g, "_")}`

  const chartConfig = useMemo(
    () =>
      ({
        change: {
          label,
          color: lineColor,
        },
      }) satisfies ChartConfig,
    [lineColor, label]
  )

  const data = useMemo(() => {
    const h = hist ?? []
    if (h.length < 2) return []
    const base = h[0].value
    return h.map((p) => ({
      date: p.date,
      change: base > 0 ? ((p.value - base) / base) * 100 : 0,
    }))
  }, [hist])

  return (
    <Link href={href} className="block">
      <Card className="@container/card gap-0 bg-linear-to-t from-primary/5 to-card shadow-xs transition-colors hover:ring-accent/50 dark:bg-card">
        <CardHeader className="pb-1">
          <CardDescription>{label}</CardDescription>
          <CardTitle
            className={`text-base font-semibold tabular-nums ${trendColor}`}
          >
            {value}
          </CardTitle>
          <CardAction>
            {change && (
              <Badge
                variant="outline"
                className={`shrink-0 whitespace-nowrap ${trendColor}`}
              >
                {TrendIcon && <TrendIcon className="size-3" />}
                {change}
              </Badge>
            )}
          </CardAction>
        </CardHeader>
        <CardContent className="px-0 pb-1 pt-0">
          {data.length >= 2 && (
            <ChartContainer
              config={chartConfig}
              className="h-[60px] w-full aspect-auto"
            >
              <AreaChart data={data} margin={{ top: 4, right: 0, bottom: 0, left: 0 }}>
                <defs>
                  <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor={lineColor} stopOpacity={0.8} />
                    <stop offset="95%" stopColor={lineColor} stopOpacity={0.1} />
                  </linearGradient>
                </defs>
                <XAxis dataKey="date" hide />
                <Area
                  type="monotone"
                  dataKey="change"
                  stroke="var(--color-change)"
                  fill={`url(#${gradientId})`}
                  strokeWidth={1.5}
                  dot={false}
                  isAnimationActive={false}
                />
                <ChartTooltip
                  cursor={false}
                  content={
                    <ChartTooltipContent
                      labelFormatter={(label) => {
                        const d = new Date(label)
                        return `${d.getMonth() + 1}月${d.getDate()}日`
                      }}
                      formatter={(value) => [
                        `${Number(value).toFixed(2)}%`,
                        label,
                      ]}
                    />
                  }
                />
              </AreaChart>
            </ChartContainer>
          )}
        </CardContent>
      </Card>
    </Link>
  )
}
