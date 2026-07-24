/**
 * 情绪雷达图（shadcn charts RadarChart）
 * - 6 维情绪评分（0-100），来自 backend /api/sentiment
 */
"use client";

import {
  PolarAngleAxis,
  PolarGrid,
  PolarRadiusAxis,
  Radar,
  RadarChart,
} from "recharts";

import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart";

export interface SentimentDim {
  key: string;
  label: string;
  value: number;
}

const chartConfig = {
  value: {
    label: "情绪",
    color: "var(--accent)",
  },
} satisfies ChartConfig;

export function SentimentRadarChart({ dims }: { dims: SentimentDim[] }) {
  return (
    <ChartContainer
      config={chartConfig}
      className="mx-auto aspect-square h-[220px] w-full max-w-[280px]"
    >
      <RadarChart data={dims} outerRadius="72%">
        <PolarGrid stroke="var(--border-strong)" />
        <PolarAngleAxis
          dataKey="label"
          tick={{ fontSize: 10, fill: "var(--fg-dim)" }}
        />
        <PolarRadiusAxis domain={[0, 100]} tick={false} axisLine={false} />
        <Radar
          dataKey="value"
          stroke="var(--color-value)"
          fill="var(--color-value)"
          fillOpacity={0.35}
          strokeWidth={2}
        />
        <ChartTooltip
          cursor={false}
          content={<ChartTooltipContent indicator="dot" />}
        />
      </RadarChart>
    </ChartContainer>
  );
}
