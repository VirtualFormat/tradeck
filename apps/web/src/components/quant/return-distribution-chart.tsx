"use client";

/**
 * 回测收益分布直方图（阶段 K4）：按单笔收益区间分桶计数
 * 正收益 var(--up) 红 / 负收益 var(--down) 绿 / 跨零桶中性色
 */
import { Bar, BarChart, CartesianGrid, Cell, XAxis, YAxis } from "recharts";

import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart";

import { fmtPct, type ReturnDistBucket } from "./types";

const chartConfig = {
  count: {
    label: "笔数",
    color: "var(--chart-1)",
  },
} satisfies ChartConfig;

export function ReturnDistributionChart({
  data,
}: {
  data: ReturnDistBucket[];
}) {
  const chartData = data.map((b) => {
    const positive = b.bucket_start >= 0;
    const negative = b.bucket_end <= 0;
    // 超界标注（P2）：±20% 之外的样本被后端 clip 并入最外桶，
    // 区间文案加「+」明示该桶含超界交易（bucket 区间本身是 ±0.20 边界）
    const isOverflow = b.bucket_start <= -0.2 || b.bucket_end >= 0.2;
    const rangeLabel = isOverflow
      ? `${fmtPct(b.bucket_start)} ~ ${fmtPct(b.bucket_end)}+`
      : `${fmtPct(b.bucket_start)} ~ ${fmtPct(b.bucket_end)}`;
    return {
      bucket: rangeLabel,
      count: b.count,
      fill:
        positive
          ? "var(--up)"
          : negative
            ? "var(--down)"
            : "var(--muted-foreground)",
    };
  });

  return (
    <ChartContainer
      config={chartConfig}
      className="aspect-auto h-[240px] w-full"
    >
      <BarChart data={chartData} margin={{ top: 4, right: 8, bottom: 0, left: 8 }}>
        <CartesianGrid vertical={false} />
        <XAxis
          dataKey="bucket"
          tickLine={false}
          axisLine={false}
          tickMargin={8}
          angle={-45}
          textAnchor="end"
          height={56}
          interval={0}
          tick={{ fontSize: 10 }}
        />
        <YAxis
          tickLine={false}
          axisLine={false}
          tickMargin={8}
          width={40}
          allowDecimals={false}
        />
        <ChartTooltip content={<ChartTooltipContent indicator="dot" />} />
        <Bar dataKey="count" radius={[3, 3, 0, 0]} isAnimationActive={false}>
          {chartData.map((d) => (
            <Cell key={d.bucket} fill={d.fill} />
          ))}
        </Bar>
      </BarChart>
    </ChartContainer>
  );
}
