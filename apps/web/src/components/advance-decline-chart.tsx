"use client"

/**
 * 涨跌半环对比图（shadcn demo「Radial Chart - Stacked」的等效实现）
 * - 单条上半环（180° → 0°）内，涨（红）、跌（绿）两段按占比分配弧长，直接对比
 * - 圆心大数字 = 涨跌家数合计，下方小字 = 涨/跌明细
 * - 注：recharts 3.x 的 RadialBar stackId 在本版本只渲染第一段，故用 Pie 半环实现
 * - 平/缺数据不绘制（仅计入底部样本数）；无 Card 外壳（由 board 统一布局）
 */
import { Cell, Pie, PieChart } from "recharts"

import { cn } from "@/lib/utils"
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart"
import { EmptyState } from "@/components/empty-state"

export interface AdvanceDeclineData {
  up: number
  down: number
  flat: number
}

interface AdvanceDeclineChartProps {
  /** 市场名（美股/港股/A股）；不传则不渲染标题行（调用方自带标题时） */
  label?: string
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
} satisfies ChartConfig

export function AdvanceDeclineChart({
  label,
  data,
  className,
}: AdvanceDeclineChartProps) {
  // 只显示涨跌：环由 涨+跌 构成（平/缺数据不参与，仅计入底部样本数）
  const total = data.up + data.down
  const sample = total + data.flat
  const advDec = total > 0 ? (data.up / total).toFixed(2) : "—"

  // 单环双色段：两个 slice（涨/跌）构成上半环，弧长按占比分配（demo「Radial Chart - Stacked」视觉效果；
  // 注：recharts 3.x 的 RadialBar stackId 在本版本下只渲染第一段，故用 Pie 半环实现同一样式）
  const chartData = [
    { name: "up", value: data.up, fill: "var(--color-up)" },
    { name: "down", value: data.down, fill: "var(--color-down)" },
  ]

  return (
    <div className={cn("flex flex-col", className)}>
      {label ? (
        <div className="text-center text-sm font-medium text-fg-dim">
          {label}
        </div>
      ) : null}
      {total === 0 ? (
        <EmptyState compact title="无数据" className="h-[180px] w-full" />
      ) : (
        <>
          <div className="relative mx-auto aspect-square w-full max-w-[200px]">
            <ChartContainer
              config={chartConfig}
              className="aspect-square h-full w-full"
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
                        const key = String(name ?? "")
                        const text =
                          chartConfig[key as keyof typeof chartConfig]?.label ??
                          key
                        return (
                          <div className="flex w-full flex-1 items-center justify-between gap-3 leading-none">
                            <span className="text-muted-foreground">{text}</span>
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
                  startAngle={180}
                  endAngle={0}
                  innerRadius="62%"
                  outerRadius="86%"
                  cornerRadius={5}
                  strokeWidth={0}
                  isAnimationActive={false}
                >
                  {chartData.map((entry) => (
                    <Cell key={entry.name} fill={entry.fill} />
                  ))}
                </Pie>
              </PieChart>
            </ChartContainer>
            {/* 圆心文字（HTML 覆盖，position 由外层 relative 提供） */}
            <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
              <span className="text-xl font-bold text-foreground tabular-nums">
                {total}
              </span>
              <span className="text-[10px] text-muted-foreground tabular-nums">
                涨 {data.up} · 跌 {data.down}
              </span>
            </div>
          </div>
          <div className="flex flex-col items-center gap-0.5 pt-1 text-[10px] text-muted-foreground tabular-nums">
            <div className="flex items-center gap-3">
              <span className="flex items-center gap-1 whitespace-nowrap">
                <span
                  className="h-2 w-2 shrink-0 rounded-[2px]"
                  style={{ backgroundColor: "var(--color-up)" }}
                />
                涨 {data.up}
              </span>
              <span className="flex items-center gap-1 whitespace-nowrap">
                <span
                  className="h-2 w-2 shrink-0 rounded-[2px]"
                  style={{ backgroundColor: "var(--color-down)" }}
                />
                跌 {data.down}
              </span>
            </div>
            <div className="whitespace-nowrap">
              样本 {sample} 只 · A/D {advDec}
            </div>
          </div>
        </>
      )}
    </div>
  )
}
