/**
 * 首页异动榜交互层
 * 仅在 RSC 已传入的四组数据之间切换，不发起网络请求。
 */
"use client";

import { useMemo, useState } from "react";
import Link from "next/link";

import type { MoversData } from "@/components/dashboard/movers-panel";
import { MoversTable } from "@/components/dashboard/movers-table";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs";
import type { MoversMarket, MoversType } from "@/lib/openbb";

const TYPES: { value: MoversType; label: string }[] = [
  { value: "gainers", label: "涨幅榜" },
  { value: "losers", label: "跌幅榜" },
  { value: "active", label: "活跃榜" },
  { value: "turnover", label: "换手榜" },
];

function isCurrentData(type: MoversType, market: MoversMarket): boolean {
  return type === "turnover" || market !== "us";
}

function shortDate(value: string | null | undefined): string | null {
  if (!value) return null;
  const match = value.match(/^\d{4}-(\d{2})-(\d{2})/);
  return match ? `${match[1]}-${match[2]}` : null;
}

function shortTime(value: string | null | undefined): string | null {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: "Asia/Shanghai",
  }).format(date);
}

function getDataLabel(
  type: MoversType,
  market: MoversMarket,
  date: string | undefined,
  data: MoversData
): string {
  const first = data[type][0];

  // 换手榜全部来自当前报价；CN/HK 三榜也是跟踪标的当前报价。
  if (isCurrentData(type, market)) {
    const time = shortTime(first?.updated_at);
    return time ? `当前 · ${time}` : "当前";
  }

  const snapshot = shortDate(first?.snapshot_date) ?? shortDate(date);
  return snapshot ? `快照 · ${snapshot}` : "最近快照";
}

export function MoversTabs({
  market,
  date,
  data,
}: {
  market: MoversMarket;
  date?: string;
  data: MoversData;
}) {
  const [activeType, setActiveType] = useState<MoversType>("gainers");
  const currentData = isCurrentData(activeType, market);
  const dataLabel = useMemo(
    () => getDataLabel(activeType, market, date, data),
    [activeType, market, date, data]
  );
  const scopeLabel =
    market === "us" && activeType !== "turnover"
      ? "全市场"
      : activeType === "turnover"
        ? "报价覆盖"
        : "跟踪标的";
  const historicalNote =
    date && currentData ? "当前数据不随历史快照切换" : null;
  const moreHref =
    market === "us"
      ? "/markets/us"
      : market === "hk"
        ? "/markets/hk"
        : "/markets/cn";
  const moreParams = new URLSearchParams();
  if (date) moreParams.set("date", date);
  const moreUrl = moreParams.size
    ? `${moreHref}?${moreParams.toString()}`
    : moreHref;

  return (
    <Tabs
      value={activeType}
      onValueChange={(value) => setActiveType(value as MoversType)}
      className="gap-0"
    >
      <Card
        size="sm"
        className="gap-0 bg-card py-3 shadow-xs md:min-h-[224px]"
      >
        <CardHeader className="gap-2 px-4 pb-1 md:flex md:h-[30px] md:flex-row md:items-center md:justify-between">
          <div className="flex min-w-0 items-center gap-2 overflow-x-auto">
            <CardTitle className="shrink-0 text-sm">异动榜</CardTitle>
            <TabsList
              aria-label="异动榜类型"
              className="h-7 min-w-max bg-transparent p-0"
            >
              {TYPES.map((type) => (
                <TabsTrigger
                  key={type.value}
                  value={type.value}
                  className="h-6 flex-none px-2 text-[11px] data-active:bg-secondary data-active:text-foreground data-active:shadow-none"
                >
                  {type.label}
                </TabsTrigger>
              ))}
            </TabsList>
          </div>

          <div className="flex min-w-0 items-center justify-between gap-2 md:shrink-0 md:justify-end">
            <div className="flex min-w-0 flex-wrap items-center gap-x-1.5 gap-y-0.5">
              <Badge
                variant="secondary"
                className="h-5 shrink-0 px-2 text-[10px] font-medium"
              >
                {scopeLabel}
              </Badge>
              <CardDescription className="text-[10px]">
                {dataLabel}
              </CardDescription>
              {historicalNote ? (
                <CardDescription className="w-full text-[10px] leading-none md:w-auto">
                  {historicalNote}
                </CardDescription>
              ) : null}
            </div>

            <Link
              href={moreUrl}
              className="shrink-0 text-[11px] text-muted-foreground transition-colors hover:text-foreground focus-visible:rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
            >
              更多 →
            </Link>
          </div>
        </CardHeader>

        <CardContent className="min-h-0 px-0">
          {TYPES.map((type) => (
            <TabsContent
              key={type.value}
              value={type.value}
              className="m-0"
            >
              <MoversTable type={type.value} items={data[type.value]} />
            </TabsContent>
          ))}
        </CardContent>
      </Card>
    </Tabs>
  );
}
