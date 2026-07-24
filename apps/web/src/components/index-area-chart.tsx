/**
 * 大盘指数相对走势 AreaChart（shadcn charts）
 * - 接收近 N 日多指数的归一化涨跌幅（%）数据
 * - 用 ChartContainer + Recharts AreaChart，渐变填充
 * - 颜色用 var(--color-KEY) 约定（KEY = series.key，由 ChartConfig 注入）
 * - Y 轴紧凑域（dataMin/dataMax ± padding），波动更明显；图例右上角
 */
"use client";

import { Fragment } from "react";
import { Area, AreaChart, CartesianGrid, XAxis, YAxis } from "recharts";

import {
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart";

export interface IndexSeries {
  /** 数据字段名（通常是 slugified symbol，作为 dataKey 与 CSS var 后缀） */
  key: string;
  cnName: string;
  /** CSS 颜色，例如 "var(--chart-1)" */
  color: string;
}

export interface IndexAreaChartProps {
  /** 每条数据：{ date: string, [series.key]: number | null } */
  data: Array<Record<string, string | number | null>>;
  series: IndexSeries[];
}

/** 把 symbol 里的特殊字符（^ .）替换成合法的 CSS id 片段 */
function safeId(s: string): string {
  return s.replace(/[^a-zA-Z0-9_-]/g, "_");
}

export function IndexAreaChart({ data, series }: IndexAreaChartProps) {
  const chartConfig = Object.fromEntries(
    series.map((s) => [
      s.key,
      { label: s.cnName, color: s.color },
    ])
  ) satisfies ChartConfig;

  // 紧凑 Y 域：只包住数据波动范围 ±10%，避免 0 基线把曲线压平
  const values = data.flatMap((row) =>
    series
      .map((s) => row[s.key])
      .filter((v): v is number => typeof v === "number" && Number.isFinite(v))
  );
  const dataMin = values.length ? Math.min(...values) : -1;
  const dataMax = values.length ? Math.max(...values) : 1;
  const pad = Math.max((dataMax - dataMin) * 0.1, 0.05);
  const domain: [number, number] = [dataMin - pad, dataMax + pad];

  return (
    <ChartContainer
      config={chartConfig}
      className="aspect-auto h-[260px] w-full"
    >
      <AreaChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
        <defs>
          {series.map((s) => {
            const gradId = `fill-${safeId(s.key)}`;
            return (
              <linearGradient
                key={gradId}
                id={gradId}
                x1="0"
                y1="0"
                x2="0"
                y2="1"
              >
                <stop
                  offset="5%"
                  stopColor={`var(--color-${s.key})`}
                  stopOpacity={0.35}
                />
                <stop
                  offset="95%"
                  stopColor={`var(--color-${s.key})`}
                  stopOpacity={0.02}
                />
              </linearGradient>
            );
          })}
        </defs>
        <CartesianGrid vertical={false} />
        <XAxis
          dataKey="date"
          tickLine={false}
          axisLine={false}
          tickMargin={8}
          minTickGap={32}
          tickFormatter={(value: string) => {
            const date = new Date(value);
            if (Number.isNaN(date.getTime())) return value;
            return date.toLocaleDateString("zh-CN", {
              month: "numeric",
              day: "numeric",
            });
          }}
        />
        <YAxis
          domain={domain}
          tickLine={false}
          axisLine={false}
          tickMargin={4}
          width={52}
          tickCount={5}
          tickFormatter={(value: number) =>
            `${value > 0 ? "+" : ""}${value.toFixed(1)}%`
          }
        />
        <ChartTooltip
          cursor={false}
          content={
            <ChartTooltipContent
              labelFormatter={(value) =>
                typeof value === "string" && !Number.isNaN(new Date(value).getTime())
                  ? new Date(value).toLocaleDateString("zh-CN", {
                      month: "long",
                      day: "numeric",
                    })
                  : String(value)
              }
              formatter={(value) => {
                const num = typeof value === "number" ? value : Number(value);
                if (!Number.isFinite(num)) return "—";
                const sign = num > 0 ? "+" : "";
                return `${sign}${num.toFixed(2)}%`;
              }}
              indicator="dot"
            />
          }
        />
        <ChartLegend
          verticalAlign="top"
          align="right"
          content={<ChartLegendContent verticalAlign="top" />}
        />
        {series.map((s) => (
          <Fragment key={s.key}>
            <Area
              dataKey={s.key}
              type="natural"
              fill={`url(#fill-${safeId(s.key)})`}
              stroke={`var(--color-${s.key})`}
              strokeWidth={1.5}
              connectNulls
            />
          </Fragment>
        ))}
      </AreaChart>
    </ChartContainer>
  );
}
