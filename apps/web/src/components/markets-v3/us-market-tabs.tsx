"use client";

import {
  useState,
  type KeyboardEvent,
  type ReactNode,
} from "react";

import { EmptyState } from "@/components/empty-state";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type {
  EarningsCalendarItem,
  EconomicCalendarItem,
} from "@/lib/openbb";
import { cn } from "@/lib/utils";

type UsMarketTab = "movers" | "sectors" | "cross-asset" | "events";

interface UsMarketTabsProps {
  movers: ReactNode;
  sectors: ReactNode;
  ratePressure: ReactNode;
  crossAsset: ReactNode;
  events: ReactNode;
}

const TABS: { value: UsMarketTab; label: string }[] = [
  { value: "movers", label: "异动" },
  { value: "sectors", label: "板块" },
  { value: "cross-asset", label: "跨资产" },
  { value: "events", label: "事件" },
];

function sessionLabel(value: string | null): string {
  const session = value?.trim().toUpperCase();
  if (session === "BMO") return "盘前";
  if (session === "AMC") return "盘后";
  return "待定";
}

function sessionCode(value: string | null): string {
  return value?.trim().toUpperCase() || "TBD";
}

function compareAscii(a: string, b: string): number {
  if (a < b) return -1;
  if (a > b) return 1;
  return 0;
}

function importanceRank(value: string | null): number {
  const normalized = value?.trim().toLowerCase();
  if (normalized === "高" || normalized === "high" || normalized === "3") {
    return 0;
  }
  if (
    normalized === "中" ||
    normalized === "medium" ||
    normalized === "2"
  ) {
    return 1;
  }
  return 2;
}

function shortDate(value: string | null): string {
  return value ? value.slice(5) : "待定";
}

function UsEventsCard({
  earnings,
  economic,
  today,
}: {
  earnings: EarningsCalendarItem[];
  economic: EconomicCalendarItem[];
  today: string;
}) {
  const rows = [
    ...earnings
      .filter((item) => item.report_date && item.report_date >= today)
      .sort((a, b) =>
        compareAscii(
          `${a.report_date ?? ""}|${sessionCode(a.session)}|${a.symbol}`,
          `${b.report_date ?? ""}|${sessionCode(b.session)}|${b.symbol}`
        )
      )
      .slice(0, 4)
      .map((item) => ({
        key: `earning-${item.report_date}-${sessionCode(item.session)}-${item.symbol}`,
        sortKey: `${item.report_date ?? ""}|0|${sessionCode(item.session)}|${item.symbol}`,
        badge: `${shortDate(item.report_date)} ${sessionLabel(item.session)}`,
        title: `${item.symbol} 财报`,
        tone: "text-up",
      })),
    ...economic
      .filter(
        (item) =>
          item.event_date &&
          item.event_date >= today &&
          item.event_name?.trim() &&
          importanceRank(item.importance) <= 1
      )
      .sort((a, b) => {
        const importance =
          importanceRank(a.importance) - importanceRank(b.importance);
        if (importance !== 0) return importance;
        return compareAscii(
          `${a.event_date ?? ""}|${a.event_time?.trim() ?? ""}`,
          `${b.event_date ?? ""}|${b.event_time?.trim() ?? ""}`
        );
      })
      .slice(0, 4)
      .map((item, index) => ({
        key: `economic-${item.event_date}-${item.event_name}-${index}`,
        sortKey: `${item.event_date ?? ""}|1|${item.event_time?.trim() ?? ""}|${importanceRank(item.importance)}`,
        badge: `${shortDate(item.event_date)} ${item.event_time?.trim() || "全天"}`,
        title: item.event_name?.trim() ?? "",
        tone: importanceRank(item.importance) === 0 ? "text-warn" : "text-fg-dim",
      })),
  ]
    .sort((a, b) => compareAscii(a.sortKey, b.sortKey))
    .slice(0, 6);

  return (
    <Card size="sm" className="gap-1.5 py-3 shadow-none">
      <CardHeader className="px-3.5">
        <CardTitle className="text-xs font-semibold text-fg-dim">
          财报与事件
        </CardTitle>
      </CardHeader>
      <CardContent className="px-3.5">
        {rows.length > 0 ? (
          <div className="flex flex-col">
            {rows.map((row) => (
              <div
                key={row.key}
                className="flex min-h-8 min-w-0 items-center gap-2 border-b border-border/60 py-1 last:border-b-0"
              >
                <Badge
                  variant="secondary"
                  className="h-4 shrink-0 rounded-sm px-1.5 py-0 font-mono text-[9px] font-medium tabular-nums"
                >
                  {row.badge}
                </Badge>
                <span className={cn("min-w-0 flex-1 truncate text-xs", row.tone)}>
                  {row.title}
                </span>
              </div>
            ))}
          </div>
        ) : (
          <EmptyState
            compact
            title="近期暂无美股财报或重要事件"
            className="min-h-28 justify-center"
          />
        )}
      </CardContent>
    </Card>
  );
}

function UsNewsCoverageCard() {
  return (
    <Card size="sm" className="gap-1.5 py-3 shadow-none">
      <CardHeader className="px-3.5">
        <CardTitle className="text-xs font-semibold text-fg-dim">
          热门资讯
        </CardTitle>
      </CardHeader>
      <CardContent className="px-3.5">
        <EmptyState
          compact
          title="美股资讯聚合待补充"
          description="现有 DashboardNews 混合 A 股与美股，暂不在单市场页冒充纯美股资讯"
          className="min-h-28 justify-center"
        />
      </CardContent>
    </Card>
  );
}

export function UsMarketContext({
  earnings,
  economic,
  today,
}: {
  earnings: EarningsCalendarItem[];
  economic: EconomicCalendarItem[];
  today: string;
}) {
  return (
    <div className="flex min-w-0 flex-col gap-3.5">
      <UsEventsCard earnings={earnings} economic={economic} today={today} />
      <UsNewsCoverageCard />
    </div>
  );
}

/**
 * 美股页 V3 响应式内容编排。
 * 同一份业务面板在移动端用 Tabs 切换，xl 以上改为 Figma 的主列/侧栏网格，
 * 避免为两套布局重复渲染 Server Component 和重复取数。
 */
export function UsMarketTabs({
  movers,
  sectors,
  ratePressure,
  crossAsset,
  events,
}: UsMarketTabsProps) {
  const [activeTab, setActiveTab] = useState<UsMarketTab>("movers");
  const handleTabKeyDown = (
    event: KeyboardEvent<HTMLButtonElement>,
    currentIndex: number
  ) => {
    let nextIndex = currentIndex;
    if (event.key === "ArrowRight") {
      nextIndex = (currentIndex + 1) % TABS.length;
    } else if (event.key === "ArrowLeft") {
      nextIndex = (currentIndex - 1 + TABS.length) % TABS.length;
    } else if (event.key === "Home") {
      nextIndex = 0;
    } else if (event.key === "End") {
      nextIndex = TABS.length - 1;
    } else {
      return;
    }

    event.preventDefault();
    const nextTab = TABS[nextIndex];
    setActiveTab(nextTab.value);
    document.getElementById(`us-market-tab-${nextTab.value}`)?.focus();
  };

  const panelClass = (
    tab: UsMarketTab,
    desktopDisplay: "block" | "contents" = "block"
  ) =>
    cn(
      activeTab === tab ? "block" : "hidden",
      "min-w-0",
      desktopDisplay === "contents" ? "xl:contents" : "xl:block"
    );

  return (
    <div className="min-w-0">
      <div
        role="tablist"
        aria-label="美股市场详情"
        className="mb-3 flex w-full gap-1 overflow-x-auto xl:hidden"
      >
        {TABS.map((tab, index) => (
          <Button
            key={tab.value}
            id={`us-market-tab-${tab.value}`}
            type="button"
            role="tab"
            aria-selected={activeTab === tab.value}
            aria-controls={`us-market-panel-${tab.value}`}
            tabIndex={activeTab === tab.value ? 0 : -1}
            variant={activeTab === tab.value ? "secondary" : "ghost"}
            size="sm"
            onClick={() => setActiveTab(tab.value)}
            onKeyDown={(event) => handleTabKeyDown(event, index)}
            className="h-7 min-w-16 flex-none px-3 text-xs"
          >
            {tab.label}
          </Button>
        ))}
      </div>

      <div className="min-w-0 xl:grid xl:grid-cols-[minmax(0,1fr)_20rem] xl:gap-4">
        <section
          id="us-market-panel-sectors"
          role="tabpanel"
          aria-labelledby="us-market-tab-sectors"
          className={cn(panelClass("sectors"), "xl:col-span-2 xl:row-start-1")}
        >
          {sectors}
        </section>

        <section
          id="us-market-panel-cross-asset"
          role="tabpanel"
          aria-labelledby="us-market-tab-cross-asset"
          className={cn(
            panelClass("cross-asset", "contents"),
            "space-y-4"
          )}
        >
          <div className="min-w-0 xl:col-span-2 xl:row-start-2 xl:mt-5">
            {ratePressure}
          </div>
          <div className="min-w-0 xl:col-start-1 xl:row-start-4 xl:mt-4">
            {crossAsset}
          </div>
        </section>

        <section
          id="us-market-panel-movers"
          role="tabpanel"
          aria-labelledby="us-market-tab-movers"
          className={cn(
            panelClass("movers"),
            "xl:col-start-1 xl:row-start-3 xl:mt-4"
          )}
        >
          {movers}
        </section>

        <section
          id="us-market-panel-events"
          role="tabpanel"
          aria-labelledby="us-market-tab-events"
          className={cn(
            panelClass("events"),
            "xl:col-start-2 xl:row-span-2 xl:row-start-3 xl:mt-4"
          )}
        >
          {events}
        </section>
      </div>
    </div>
  );
}
