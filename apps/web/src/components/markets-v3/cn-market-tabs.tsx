"use client";

import {
  useState,
  type KeyboardEvent,
  type ReactNode,
} from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type CnMarketTab = "movers" | "industries" | "funds" | "events";

interface CnMarketTabsProps {
  movers: ReactNode;
  industryDesktop: ReactNode;
  industryMobile: ReactNode;
  funds: ReactNode;
  events: ReactNode;
}

const TAB_ITEMS: { value: CnMarketTab; label: string }[] = [
  { value: "movers", label: "异动" },
  { value: "industries", label: "行业" },
  { value: "funds", label: "资金" },
  { value: "events", label: "事件" },
];

/**
 * A 股 V3 响应式编排。
 * 业务面板只挂载一次；xl 以下用一级 Tabs，xl 以上重排为主列/侧栏。
 */
export function CnMarketTabs({
  movers,
  industryDesktop,
  industryMobile,
  funds,
  events,
}: CnMarketTabsProps) {
  const [activeTab, setActiveTab] = useState<CnMarketTab>("industries");
  const panelClass = (tab: CnMarketTab) =>
    cn(activeTab === tab ? "block" : "hidden", "min-w-0 xl:block");
  const handleTabKeyDown = (
    event: KeyboardEvent<HTMLButtonElement>,
    currentIndex: number
  ) => {
    let nextIndex = currentIndex;
    if (event.key === "ArrowRight") {
      nextIndex = (currentIndex + 1) % TAB_ITEMS.length;
    } else if (event.key === "ArrowLeft") {
      nextIndex = (currentIndex - 1 + TAB_ITEMS.length) % TAB_ITEMS.length;
    } else if (event.key === "Home") {
      nextIndex = 0;
    } else if (event.key === "End") {
      nextIndex = TAB_ITEMS.length - 1;
    } else {
      return;
    }

    event.preventDefault();
    const nextTab = TAB_ITEMS[nextIndex];
    setActiveTab(nextTab.value);
    document.getElementById(`cn-market-tab-${nextTab.value}`)?.focus();
  };

  return (
    <div className="min-w-0">
      <div
        role="tablist"
        aria-label="A股市场深度"
        className="mb-3 grid grid-cols-4 gap-1 xl:hidden"
      >
        {TAB_ITEMS.map((tab, index) => (
          <Button
            key={tab.value}
            id={`cn-market-tab-${tab.value}`}
            type="button"
            role="tab"
            aria-selected={activeTab === tab.value}
            aria-controls={`cn-market-panel-${tab.value}`}
            tabIndex={activeTab === tab.value ? 0 : -1}
            variant={activeTab === tab.value ? "secondary" : "ghost"}
            size="sm"
            onClick={() => setActiveTab(tab.value)}
            onKeyDown={(event) => handleTabKeyDown(event, index)}
            className="h-8 px-2 text-xs"
          >
            {tab.label}
          </Button>
        ))}
      </div>

      <div className="min-w-0 xl:grid xl:grid-cols-[minmax(0,1fr)_32rem] xl:gap-3">
        <section
          id="cn-market-panel-industries"
          role="tabpanel"
          aria-labelledby="cn-market-tab-industries"
          className={cn(panelClass("industries"), "xl:col-start-1 xl:row-start-1")}
        >
          <div className="xl:hidden">{industryMobile}</div>
          <div className="hidden xl:block">{industryDesktop}</div>
        </section>

        <section
          id="cn-market-panel-funds"
          role="tabpanel"
          aria-labelledby="cn-market-tab-funds"
          className={cn(panelClass("funds"), "xl:col-start-1 xl:row-start-2 xl:mt-3")}
        >
          {funds}
        </section>

        <section
          id="cn-market-panel-movers"
          role="tabpanel"
          aria-labelledby="cn-market-tab-movers"
          className={cn(panelClass("movers"), "xl:col-start-2 xl:row-start-1")}
        >
          {movers}
        </section>

        <section
          id="cn-market-panel-events"
          role="tabpanel"
          aria-labelledby="cn-market-tab-events"
          className={cn(
            panelClass("events"),
            "xl:col-start-2 xl:row-span-2 xl:row-start-2 xl:mt-3"
          )}
        >
          {events}
        </section>
      </div>
    </div>
  );
}
