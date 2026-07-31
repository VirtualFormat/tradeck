import { Suspense } from "react";

import { DatePicker } from "@/components/date-picker";
import { MarketStatusBar } from "@/components/market-status-bar";
import { RefreshButton } from "@/components/refresh-button";
import { StockSearch } from "@/components/stock-search";
import { ThemeToggle } from "@/components/theme-toggle";
import { Badge } from "@/components/ui/badge";
import { SidebarTrigger } from "@/components/ui/sidebar";

type Market = "CN" | "US" | "HK";

interface MarketPageToolbarProps {
  market: Market;
  title: string;
  subtitle?: string;
  date?: string;
}

/** 市场页 V3 顶部工具栏：同一结构在窄屏分行、桌面同行。 */
export function MarketPageToolbar({
  market,
  title,
  subtitle,
  date,
}: MarketPageToolbarProps) {
  return (
    <header className="flex min-w-0 flex-col gap-3 border-b border-border/60 pb-4 xl:flex-row xl:items-center xl:gap-4">
      <div className="flex min-w-0 items-start gap-2">
        <SidebarTrigger className="mt-0.5 shrink-0" />
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="font-heading text-xl leading-7 font-semibold tracking-tight text-foreground md:text-2xl">
              {title}
            </h1>
            {date && (
              <Badge variant="secondary" className="shrink-0 tabular-nums">
                快照 · {date}
              </Badge>
            )}
          </div>
          {subtitle && (
            <p className="mt-0.5 text-xs leading-5 text-muted-foreground md:text-sm">
              {subtitle}
            </p>
          )}
        </div>
      </div>

      <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-center xl:ml-auto xl:flex-nowrap">
        <div className="min-w-0 flex-1 sm:min-w-64 xl:w-72 xl:flex-none">
          <div className="[&_[data-slot=command]]:w-full">
            <StockSearch />
          </div>
        </div>

        <div className="flex min-w-0 flex-wrap items-center gap-1">
          <DatePicker />
          <RefreshButton />
          <ThemeToggle />
        </div>

        <div className="min-w-0 basis-full border-t border-border/60 pt-2 sm:basis-auto sm:border-0 sm:pt-0">
          <Suspense fallback={null}>
            <MarketStatusBar
              market={market}
              className="ml-0 flex-wrap justify-start sm:flex-nowrap"
            />
          </Suspense>
        </div>
      </div>
    </header>
  );
}
