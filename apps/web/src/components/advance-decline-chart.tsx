"use client"

/**
 * 涨跌平 Donut PieChart（shadcn ChartContainer + Recharts PieChart）
 * 红涨绿跌（A 股习惯）：涨=var(--up) 红，跌=var(--down) 绿，平=var(--muted) 灰
 */
import { Cell, Pie, PieChart } from "recharts"

import { cn } from "@/lib/utils"
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  ChartLegend,
  type ChartConfig,
} from "@/components/ui/chart"

export interface AdvanceDeclineData {
  up: number
  down: number
  flat: number
}

interface AdvanceDeclineChartProps {
  data: AdvanceDeclineData
  className?: string
}

const chartConfig = {
  up: {
    label: "涨",
    color: "var(--up)",
  },
  down: {
    label: "跌",
    color: "var(--down)",
  },
  flat: {
    label: "平",
    color: "var(--muted)",
  },
} satisfies ChartConfig

/**
 * 自定义 Legend 内容：显示 涨/跌/平 标签 + 数量 + 占比%
 * 不依赖 recharts payload（避免 0 值切片被过滤），直接用 data prop 渲染。
 */
function AdvanceDeclineLegendContent({
  data,
  payload,
}: {
  data: AdvanceDeclineData
  payload?: Array<{ name?: string; color?: string }>
}) {
  const total = data.up + data.down + data.flat
  // 用 payload 的 color 兜底，取不到就用 CSS 变量
  const colorMap: Record<string, string> = {
    up: "var(--color-up)",
    down: "var(--color-down)",
    flat: "var(--color-flat)",
  }
  if (Array.isArray(payload)) {
    for (const item of payload) {
      if (item.name && item.color) {
        colorMap[item.name] = item.color
      }
    }
  }
  const items = [
    { key: "up" as const, label: "涨", count: data.up },
    { key: "down" as const, label: "跌", count: data.down },
    { key: "flat" as const, label: "平", count: data.flat },
  ]
  return (
    <div className="flex items-center justify-center gap-4 pt-3">
      {items.map((item) => {
        const pct = total > 0 ? (item.count / total) * 100 : 0
        return (
          <div
            key={item.key}
            className="flex items-center gap-1.5"
          >
            <div
              className="h-2 w-2 shrink-0 rounded-[2px]"
              style={{ backgroundColor: colorMap[item.key] }}
            />
            <span className="text-muted-foreground">{item.label}</span>
            <span className="font-mono font-medium text-foreground tabular-nums">
              {item.count}
            </span>
            <span className="text-[10px] text-muted-foreground tabular-nums">
              {pct.toFixed(0)}%
            </span>
          </div>
        )
      })}
    </div>
  )
}

export function AdvanceDeclineChart({
  data,
  className,
}: AdvanceDeclineChartProps) {
  const total = data.up + data.down + data.flat

  // 无数据空状态
  if (total === 0) {
    return (
      <div
        className={cn(
          "flex h-[220px] w-full items-center justify-center text-xs text-muted",
          className
        )}
      >
        无数据
      </div>
    )
  }

  const chartData = [
    { name: "up", value: data.up, fill: "var(--color-up)" },
    { name: "down", value: data.down, fill: "var(--color-down)" },
    { name: "flat", value: data.flat, fill: "var(--color-flat)" },
  ]

  return (
    <ChartContainer
      config={chartConfig}
      className={cn("aspect-auto h-[220px] w-full", className)}
    >
      <PieChart>
        <ChartTooltip
          cursor={false}
          content={
            <ChartTooltipContent
              hideLabel
              formatter={(value, name) => {
                const num =
                  typeof value === "number" ? value : Number(value) || 0
                const pct = total > 0 ? (num / total) * 100 : 0
                const labelKey = String(name ?? "")
                const label =
                  chartConfig[labelKey as keyof typeof chartConfig]?.label ??
                  labelKey
                return (
                  <div className="flex w-full flex-1 items-center justify-between gap-3 leading-none">
                    <span className="text-muted-foreground">{label}</span>
                    <span className="font-mono font-medium text-foreground tabular-nums">
                      {num} ({pct.toFixed(1)}%)
                    </span>
                  </div>
                )
              }}
            />
          }
        />
        <Pie
          data={chartData}
          dataKey="value"
          nameKey="name"
          innerRadius={50}
          outerRadius={80}
          paddingAngle={2}
          strokeWidth={0}
        >
          {chartData.map((entry) => (
            <Cell key={entry.name} fill={entry.fill} />
          ))}
        </Pie>
        <ChartLegend
          content={<AdvanceDeclineLegendContent data={data} />}
        />
      </PieChart>
    </ChartContainer>
  )
}
