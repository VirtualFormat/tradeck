import { Suspense } from "react";

import { DatePicker } from "@/components/date-picker";
import { MarketStatusBar } from "@/components/market-status-bar";
import { RefreshButton } from "@/components/refresh-button";
import { StockSearch } from "@/components/stock-search";
import { Badge } from "@/components/ui/badge";
import { SidebarTrigger } from "@/components/ui/sidebar";

export function DashboardToolbar({ date }: { date?: string }) {
  return (
    <div
      data-dashboard-toolbar
      className="flex min-w-0 flex-col gap-2 md:flex-row md:flex-wrap md:items-center md:gap-x-3 md:gap-y-2"
    >
      <div className="flex min-w-0 flex-wrap items-center gap-2 md:contents">
        <SidebarTrigger className="hidden shrink-0 md:inline-flex" />
        <div className="min-w-0 basis-full sm:basis-auto sm:flex-1 md:max-w-72">
          <div className="[&_[data-slot=command]]:w-full">
            <StockSearch />
          </div>
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-1">
          <DatePicker />
          <RefreshButton />
        </div>
      </div>

      <div className="flex min-w-0 flex-wrap items-center gap-2 border-t border-border/60 pt-2 md:ml-auto md:border-0 md:pt-0">
        <div className="min-w-0 flex-1 md:flex-none">
          <Suspense fallback={null}>
            <MarketStatusBar className="ml-0 flex-wrap justify-start md:flex-nowrap" />
          </Suspense>
        </div>
        {date && (
          <Badge variant="secondary" className="shrink-0">
            快照模式：{date}
          </Badge>
        )}
      </div>
    </div>
  );
}
