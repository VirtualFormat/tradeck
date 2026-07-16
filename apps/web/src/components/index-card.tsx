/**
 * 单个大盘指数卡片（紧凑版，shadcn Card + mini AreaChart）
 * - mini AreaChart 显示近 7 日相对涨跌幅走势
 * - hover 显示日期 + 涨跌幅值
 * - 右上角 Badge 显示涨跌幅%
 * - tradeck 主题：红涨绿跌 text-up / text-down、tab-nums
 */
"use client";

import { useMemo } from "react";
import { Area, AreaChart, XAxis } from "recharts";
import { TrendUpIcon, TrendDownIcon } from "@phosphor-icons/react";

import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart";
import { fmtPrice, fmtPct } from "@/lib/format";

export interface IndexQuote {
  symbol: string;
  cnName: string;
  market: string;
  last_price: number | null;
  change_percent: number | null;
  currency: string | null;
  /** 近 N 日历史数据（旧 → 新） */
  hist?: { date: string; value: number }[];
}

const MARKET_LABEL: Record<string, string> = {
  us: "US",
  hk: "HK",
  cn: "CN",
};

export function IndexCard({ quote }: { quote: IndexQuote }) {
  const up = (quote.change_percent ?? 0) >= 0;
  const changeColor = up ? "text-up" : "text-down";
  const TrendIcon = up ? TrendUpIcon : TrendDownIcon;
  const marketLabel = MARKET_LABEL[quote.market] ?? quote.market;
  const lineColor = up ? "var(--up)" : "var(--down)";
  const gradientId = `fill-${quote.symbol.replace(/[^a-zA-Z0-9]/g, "_")}`;

  const chartConfig = useMemo(
    () =>
      ({
        change: {
          label: quote.cnName,
          color: lineColor,
        },
      }) satisfies ChartConfig,
    [lineColor, quote.cnName]
  );

  const data = useMemo(() => {
    const hist = quote.hist ?? [];
    if (hist.length < 2) return [];
    const base = hist[0].value;
    return hist.map((p) => ({
      date: p.date,
      change: base > 0 ? ((p.value - base) / base) * 100 : 0,
    }));
  }, [quote.hist]);

  return (
    <Card className="@container/card gap-0">
      <CardHeader className="pb-1">
        <CardDescription className="flex items-center gap-1.5">
          <span className="rounded-sm bg-border/60 px-1 text-[9px] uppercase tracking-wider text-muted">
            {marketLabel}
          </span>
          {quote.cnName}
        </CardDescription>
        <CardTitle
          className={`text-base font-semibold tabular-nums ${changeColor}`}
        >
          {fmtPrice(quote.last_price)}
        </CardTitle>
        <CardAction>
          <Badge variant="outline" className={changeColor}>
            <TrendIcon className="size-3" />
            {fmtPct(quote.change_percent)}
          </Badge>
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
                      const d = new Date(label);
                      return `${d.getMonth() + 1}月${d.getDate()}日`;
                    }}
                    formatter={(value) => [
                      `${Number(value).toFixed(2)}%`,
                      quote.cnName,
                    ]}
                  />
                }
              />
            </AreaChart>
          </ChartContainer>
        )}
      </CardContent>
    </Card>
  );
}
