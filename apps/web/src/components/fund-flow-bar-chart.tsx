/**
 * 资金流向横条图（shadcn charts BarChart - Custom Label）
 * - 横条长度 = 主力净额绝对值，名称嵌柱内（insideLeft），金额标柱端
 * - 流入红 / 流出绿（绿榜柱子向左：负值 + domain [dataMin, 0]）
 */
"use client";

import { Bar, BarChart, Cell, LabelList, XAxis, YAxis } from "recharts";

import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart";

export interface FlowBarRow {
  name: string;
  /** 主力净额（元，带符号） */
  net: number;
  /** 柱长（|net|） */
  size: number;
  changePercent: number | null;
  turnoverRate: number | null;
}

/** 金额格式化：亿/万 */
function fmtAmount(v: number): string {
  const sign = v >= 0 ? "+" : "-";
  const abs = Math.abs(v);
  if (abs >= 1e8) return `${sign}${(abs / 1e8).toFixed(1)}亿`;
  if (abs >= 1e4) return `${sign}${(abs / 1e4).toFixed(0)}万`;
  return `${sign}${abs}`;
}

const chartConfig = {
  value: {
    label: "主力净额",
  },
  inflow: {
    label: "流入",
    color: "var(--up)",
  },
  outflow: {
    label: "流出",
    color: "var(--down)",
  },
} satisfies ChartConfig;

export function FundFlowBarChart({
  rows,
  variant,
}: {
  rows: FlowBarRow[];
  variant: "in" | "out";
}) {
  const isIn = variant === "in";
  const fill = isIn ? "var(--up)" : "var(--down)";
  // 绿榜用负值让柱子向左生长
  const data = rows.map((r) => ({ ...r, value: isIn ? r.size : -r.size }));

  return (
    <ChartContainer
      config={chartConfig}
      className="aspect-auto h-[300px] w-full"
    >
      <BarChart
        data={data}
        layout="vertical"
        margin={
          isIn
            ? { top: 0, right: 56, bottom: 0, left: 0 }
            : { top: 0, right: 0, bottom: 0, left: 56 }
        }
      >
        <XAxis
          type="number"
          hide
          domain={isIn ? [0, "dataMax"] : ["dataMin", 0]}
        />
        <YAxis dataKey="name" type="category" hide />
        <ChartTooltip
          cursor={false}
          content={
            <ChartTooltipContent
              formatter={(_value, _name, item) => {
                const payload = item?.payload as FlowBarRow | undefined;
                if (!payload) return "—";
                return (
                  <div className="flex w-full flex-col gap-0.5">
                    <span className="font-mono font-medium">
                      {fmtAmount(payload.net)}
                    </span>
                    {payload.changePercent != null && (
                      <span className="text-muted-foreground">
                        涨跌幅 {payload.changePercent > 0 ? "+" : ""}
                        {payload.changePercent.toFixed(2)}%
                        {payload.turnoverRate != null
                          ? ` · 换手 ${payload.turnoverRate.toFixed(1)}%`
                          : ""}
                      </span>
                    )}
                  </div>
                );
              }}
            />
          }
        />
        <Bar dataKey="value" radius={4}>
          {/* 名称嵌柱内 */}
          <LabelList
            dataKey="name"
            position={isIn ? "insideLeft" : "insideRight"}
            offset={8}
            className="fill-white"
            fontSize={11}
          />
          {/* 金额标柱端 */}
          <LabelList
            dataKey="net"
            position={isIn ? "right" : "left"}
            offset={8}
            className="fill-fg-dim"
            fontSize={10}
            formatter={(v) => fmtAmount(Number(v))}
          />
          {data.map((entry) => (
            <Cell key={entry.name} fill={fill} />
          ))}
        </Bar>
      </BarChart>
    </ChartContainer>
  );
}
