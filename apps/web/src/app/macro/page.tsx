/**
 * 宏观工作区：市场结构 / 指标趋势 / 事件日历
 * 路由：/macro?view=structure|indicators|events
 */
import { redirect } from "next/navigation";
import { Suspense } from "react";

import { MacroEventsSection } from "@/components/macro-events-section";
import { MacroIndicatorSection } from "@/components/macro-indicator-section";
import { MacroStructureSection } from "@/components/macro-structure-section";
import { MacroViewTabs } from "@/components/macro-view-tabs";
import { StockSearch } from "@/components/stock-search";
import { RefreshButton } from "@/components/refresh-button";
import { Skeleton } from "@/components/ui/skeleton";

export const dynamic = "force-dynamic";

type MacroView = "structure" | "indicators" | "events";

const VIEW_DESCRIPTIONS: Record<MacroView, string> = {
  structure: "跨资产、利率曲线与内部结构，回答市场正在如何定价",
  indicators: "CPI、失业率、GDP 与政策利率的历史趋势和最新变化",
  events: "未来财报与宏观发布，按来源日期、预期与重要性查看",
};

function normalizeView(value: string | undefined): MacroView {
  if (value === "indicators" || value === "events") return value;
  return "structure";
}

function SectionSkeleton() {
  return (
    <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
      {Array.from({ length: 3 }).map((_, index) => (
        <Skeleton key={index} className="h-48 w-full rounded-lg" />
      ))}
    </div>
  );
}

export default async function MacroPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = await searchParams;
  const viewValue = Array.isArray(params.view) ? params.view[0] : params.view;
  const view = normalizeView(viewValue);

  // 裸 /macro 明确指向默认结构视图，避免同一路径存在两种语义。
  if (viewValue !== view) {
    redirect(`/macro?view=${view}`);
  }

  return (
    <div className="space-y-5 px-4 lg:px-6">
      <header className="flex flex-col gap-3 border-b border-border pb-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h1 className="text-lg font-semibold">宏观</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {VIEW_DESCRIPTIONS[view]}
          </p>
        </div>
        <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-center">
          <div className="min-w-0 flex-1 sm:w-80 [&_[data-slot=command]]:w-full">
            <StockSearch />
          </div>
          <RefreshButton />
        </div>
      </header>

      <MacroViewTabs
        value={view}
        structure={
          <Suspense fallback={<SectionSkeleton />}>
            <MacroStructureSection />
          </Suspense>
        }
        indicators={
          <Suspense fallback={<SectionSkeleton />}>
            <MacroIndicatorSection />
          </Suspense>
        }
        events={
          <Suspense fallback={<SectionSkeleton />}>
            <MacroEventsSection />
          </Suspense>
        }
      />
    </div>
  );
}
