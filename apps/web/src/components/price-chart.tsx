"use client";

import { Line, LineChart, CartesianGrid, XAxis } from "recharts";
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart";
import type { HistoricalPrice } from "@/lib/openbb";

/**
 * 个股价格走势图（shadcn charts LineChart）
 * 客户端组件：Recharts ResponsiveContainer 需要 DOM 测量。
 */
export function PriceChart({ data }: { data: HistoricalPrice[] }) {
  if (data.length < 2) {
    return (
      <div className="flex h-64 items-center justify-center text-muted">
        无历史数据
      </div>
    );
  }

  const up = data[data.length - 1].close >= data[0].close;
  const strokeColor = up ? "var(--up)" : "var(--down)";

  const chartData = data.map((d) => ({ date: d.date, price: d.close }));
  const chartConfig = {
    price: {
      label: "收盘价",
      color: strokeColor,
    },
  } satisfies ChartConfig;

  return (
    <ChartContainer
      config={chartConfig}
      className="aspect-auto h-[300px] w-full"
    >
      <LineChart data={chartData}>
        <CartesianGrid
          vertical={false}
          stroke="var(--border)"
          strokeDasharray="2 4"
        />
        <XAxis
          dataKey="date"
          tickLine={false}
          axisLine={false}
          tickMargin={8}
          minTickGap={32}
          tickFormatter={(value) => {
            const date = new Date(value);
            return date.toLocaleDateString("en-US", {
              month: "short",
              day: "numeric",
            });
          }}
        />
        <ChartTooltip
          cursor={false}
          content={
            <ChartTooltipContent
              labelFormatter={(value) =>
                new Date(value).toLocaleDateString("en-US", {
                  month: "short",
                  day: "numeric",
                })
              }
              indicator="line"
            />
          }
        />
        <Line
          dataKey="price"
          type="natural"
          stroke="var(--color-price)"
          strokeWidth={2}
          dot={false}
        />
      </LineChart>
    </ChartContainer>
  );
}
