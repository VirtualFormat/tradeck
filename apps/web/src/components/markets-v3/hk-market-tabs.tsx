"use client";

import {
  useState,
  type KeyboardEvent,
  type ReactNode,
} from "react";

import { EmptyState } from "@/components/empty-state";
import { StockPreviewTrigger } from "@/components/stock-preview-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import type {
  EarningsCalendarItem,
  EquityQuote,
  NewsArticle,
} from "@/lib/openbb";
import { cn } from "@/lib/utils";

type QuoteTab = "gainers" | "losers" | "active";
type HkPageTab = "quotes" | "snapshot" | "events" | "news";

const HK_PAGE_TABS: { value: HkPageTab; label: string }[] = [
  { value: "quotes", label: "代表标的" },
  { value: "snapshot", label: "市场快照" },
  { value: "events", label: "事件" },
  { value: "news", label: "资讯" },
];

interface HkMarketTabsProps {
  quotes: EquityQuote[];
  quoteRange: string;
  quoteFetchRange: string;
  quoteCoverage: number;
  quoteFreshness: HkQuoteFreshness[];
  earnings: EarningsCalendarItem[];
  news: NewsArticle[];
  snapshot: ReactNode;
  coverage: ReactNode;
}

export interface HkQuoteFreshness {
  symbol: string;
  isStale: boolean;
  cutoffLabel: string | null;
  fetchedLabel: string | null;
}

function formatPrice(value: number | null): string {
  if (value == null) return "—";
  return value.toLocaleString("en-US", {
    minimumFractionDigits: value >= 1000 ? 0 : 2,
    maximumFractionDigits: value >= 1000 ? 0 : 2,
  });
}

function formatPercent(value: number | null): string {
  if (value == null) return "—";
  return `${value > 0 ? "+" : ""}${(value * 100).toFixed(2)}%`;
}

function formatAmount(quote: EquityQuote): string {
  if (quote.last_price == null || quote.volume == null) return "—";
  const value = quote.last_price * quote.volume;
  if (value >= 1e9) return `${(value / 1e9).toFixed(2)}B`;
  if (value >= 1e6) return `${(value / 1e6).toFixed(2)}M`;
  return value.toLocaleString("en-US");
}

function changeClass(value: number | null): string {
  if (value == null || value === 0) return "text-muted-foreground";
  return value > 0 ? "text-up" : "text-down";
}

function sortQuotes(quotes: EquityQuote[], type: QuoteTab): EquityQuote[] {
  return [...quotes].sort((a, b) => {
    if (type === "active") {
      return (
        (b.last_price ?? 0) * (b.volume ?? 0) -
        (a.last_price ?? 0) * (a.volume ?? 0)
      );
    }
    const aValue = a.change_percent;
    const bValue = b.change_percent;
    if (aValue == null) return 1;
    if (bValue == null) return -1;
    return type === "gainers" ? bValue - aValue : aValue - bValue;
  });
}

function RepresentativeQuotes({
  quotes,
  quoteRange,
  quoteFetchRange,
  quoteCoverage,
  quoteFreshness,
}: {
  quotes: EquityQuote[];
  quoteRange: string;
  quoteFetchRange: string;
  quoteCoverage: number;
  quoteFreshness: HkQuoteFreshness[];
}) {
  const [type, setType] = useState<QuoteTab>("gainers");
  const rows = sortQuotes(quotes, type).slice(0, 8);
  const freshnessBySymbol = new Map(
    quoteFreshness.map((item) => [item.symbol, item])
  );

  return (
    <Card size="sm" className="gap-3 py-3.5">
      <CardHeader className="gap-2 px-3.5 md:px-4">
        <div>
          <CardTitle>代表标的 · 当前报价快照</CardTitle>
          <CardDescription className="text-[11px]">
            行情截止 {quoteRange} · 覆盖 {quoteCoverage}/12 · 抓取 {quoteFetchRange}；非全市场榜单
          </CardDescription>
        </div>
        <div className="flex gap-1">
          {(["gainers", "losers", "active"] as QuoteTab[]).map((value) => (
            <Button
              key={value}
              type="button"
              aria-pressed={type === value}
              variant={type === value ? "secondary" : "ghost"}
              size="xs"
              onClick={() => setType(value)}
            >
              {value === "gainers" ? "涨幅" : value === "losers" ? "跌幅" : "活跃"}
            </Button>
          ))}
        </div>
      </CardHeader>
      <CardContent className="px-3.5 md:px-4">
        {rows.length ? (
          <div className="divide-y divide-border/60">
            {rows.map((quote) => {
              const freshness = freshnessBySymbol.get(quote.symbol);
              const isStale = freshness?.isStale ?? true;
              const cutoff = freshness?.cutoffLabel ?? null;
              const fetched = freshness?.fetchedLabel ?? null;

              return (
                <StockPreviewTrigger
                  key={quote.symbol}
                  symbol={quote.symbol}
                  name={quote.name}
                  renderTrigger={(triggerProps) => (
                    <div
                      onClick={triggerProps.onClick}
                      className="flex min-w-0 cursor-pointer items-center gap-2 py-2"
                    >
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={(event) => {
                          event.stopPropagation();
                          triggerProps.onClick(event);
                        }}
                        className="-ml-2 h-auto min-w-0 flex-1 justify-start px-2 py-1"
                      >
                        <span className="min-w-0 truncate text-left text-xs">
                          <span className="font-medium tabular-nums">
                            {quote.symbol.replace(".HK", "")}
                          </span>
                          <span className="ml-2 text-muted-foreground">
                            {quote.name || quote.symbol}
                          </span>
                        </span>
                      </Button>
                      <span className="w-16 shrink-0 text-right text-xs tabular-nums">
                        {formatPrice(quote.last_price)}
                      </span>
                      <span
                        className={cn(
                          "w-28 shrink-0 text-right text-xs font-medium tabular-nums",
                          changeClass(quote.change_percent)
                        )}
                      >
                        {formatPercent(quote.change_percent)}
                        <span
                          className={cn(
                            "block text-[9px] font-normal",
                            isStale ? "text-warn" : "text-muted-foreground"
                          )}
                        >
                          {cutoff
                            ? `${isStale ? "陈旧 · " : ""}行情截止 ${cutoff}`
                            : "行情时间未知"}
                        </span>
                        <span className="block text-[9px] font-normal text-muted-foreground">
                          {fetched ? `抓取 ${fetched}` : "抓取时间未知"}
                        </span>
                        {type === "active" && (
                          <span className="block text-[9px] font-normal text-muted-foreground">
                            估算 {formatAmount(quote)}
                          </span>
                        )}
                      </span>
                    </div>
                  )}
                />
              );
            })}
          </div>
        ) : (
          <EmptyState compact title="暂无代表标的报价" className="min-h-40" />
        )}
      </CardContent>
    </Card>
  );
}

function EventsPanel({ earnings }: { earnings: EarningsCalendarItem[] }) {
  const rows = earnings.filter((item) => item.symbol.endsWith(".HK")).slice(0, 6);
  return (
    <ListCard title="公司事件" description="未来财报日历 · 代表标的覆盖">
      {rows.length ? (
        rows.map((item) => (
          <div key={`${item.symbol}-${item.report_date}`} className="flex gap-2 border-b py-2 text-xs last:border-0">
            <Badge variant="secondary">{item.report_date?.slice(5) ?? "待定"}</Badge>
            <span>{item.symbol.replace(".HK", "")} 财报</span>
          </div>
        ))
      ) : (
        <EmptyState compact title="暂无港股公司事件" className="min-h-28" />
      )}
    </ListCard>
  );
}

function NewsPanel({ news }: { news: NewsArticle[] }) {
  return (
    <ListCard title="港股资讯" description="代表标的新闻覆盖有限">
      {news.length ? (
        news.slice(0, 6).map((article) => (
          <a
            key={article.url}
            href={article.url}
            target="_blank"
            rel="noopener noreferrer"
            className="flex gap-2 border-b py-2 text-xs last:border-0"
          >
            <Badge variant="secondary">
              {article.symbol.replace(".HK", "")}
            </Badge>
            <span className="line-clamp-2 text-fg-dim">{article.title}</span>
          </a>
        ))
      ) : (
        <EmptyState compact title="暂无港股资讯" className="min-h-28" />
      )}
    </ListCard>
  );
}

function ListCard({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children: ReactNode;
}) {
  return (
    <Card size="sm" className="gap-2 py-3">
      <CardHeader className="gap-0.5 px-3.5">
        <CardTitle>{title}</CardTitle>
        <CardDescription className="text-[11px]">{description}</CardDescription>
      </CardHeader>
      <CardContent className="px-3.5">{children}</CardContent>
    </Card>
  );
}

/** 港股 V3：单 DOM 在移动 Tabs 与桌面主列/侧栏之间响应式重排。 */
export function HkMarketTabs({
  quotes,
  quoteRange,
  quoteFetchRange,
  quoteCoverage,
  quoteFreshness,
  earnings,
  news,
  snapshot,
  coverage,
}: HkMarketTabsProps) {
  const [activeTab, setActiveTab] = useState<HkPageTab>("quotes");
  const panelClass = (tab: HkPageTab) =>
    cn(activeTab === tab ? "block" : "hidden", "min-w-0 xl:block");
  const handleTabKeyDown = (
    event: KeyboardEvent<HTMLButtonElement>,
    currentIndex: number
  ) => {
    let nextIndex = currentIndex;
    if (event.key === "ArrowRight") {
      nextIndex = (currentIndex + 1) % HK_PAGE_TABS.length;
    } else if (event.key === "ArrowLeft") {
      nextIndex =
        (currentIndex - 1 + HK_PAGE_TABS.length) % HK_PAGE_TABS.length;
    } else if (event.key === "Home") {
      nextIndex = 0;
    } else if (event.key === "End") {
      nextIndex = HK_PAGE_TABS.length - 1;
    } else {
      return;
    }

    event.preventDefault();
    const nextTab = HK_PAGE_TABS[nextIndex];
    setActiveTab(nextTab.value);
    document.getElementById(`hk-market-tab-${nextTab.value}`)?.focus();
  };

  return (
    <div className="min-w-0">
      <div
        role="tablist"
        aria-label="港股市场详情"
        className="mb-3 flex gap-1 overflow-x-auto xl:hidden"
      >
        {HK_PAGE_TABS.map((tab, index) => (
          <Button
            key={tab.value}
            id={`hk-market-tab-${tab.value}`}
            type="button"
            role="tab"
            aria-selected={activeTab === tab.value}
            aria-controls={`hk-market-panel-${tab.value}`}
            tabIndex={activeTab === tab.value ? 0 : -1}
            variant={activeTab === tab.value ? "secondary" : "ghost"}
            size="sm"
            onClick={() => setActiveTab(tab.value)}
            onKeyDown={(event) => handleTabKeyDown(event, index)}
            className="flex-none"
          >
            {tab.label}
          </Button>
        ))}
      </div>

      <div className="min-w-0 xl:grid xl:grid-cols-[minmax(0,1fr)_20rem] xl:gap-4">
        <section
          id="hk-market-panel-quotes"
          role="tabpanel"
          aria-labelledby="hk-market-tab-quotes"
          className={cn(panelClass("quotes"), "xl:col-start-1 xl:row-start-1")}
        >
          <RepresentativeQuotes
            quotes={quotes}
            quoteRange={quoteRange}
            quoteFetchRange={quoteFetchRange}
            quoteCoverage={quoteCoverage}
            quoteFreshness={quoteFreshness}
          />
        </section>
        <section
          id="hk-market-panel-snapshot"
          role="tabpanel"
          aria-labelledby="hk-market-tab-snapshot"
          className={cn(panelClass("snapshot"), "space-y-4 xl:col-start-1 xl:row-start-2 xl:mt-4")}
        >
          {snapshot}
        </section>
        <aside className="contents">
          <section
            id="hk-market-panel-news"
            role="tabpanel"
            aria-labelledby="hk-market-tab-news"
            className={cn(panelClass("news"), "xl:col-start-2 xl:row-start-1")}
          >
            <NewsPanel news={news} />
          </section>
          <section
            id="hk-market-panel-events"
            role="tabpanel"
            aria-labelledby="hk-market-tab-events"
            className={cn(panelClass("events"), "xl:col-start-2 xl:row-start-2 xl:mt-4")}
          >
            <EventsPanel earnings={earnings} />
          </section>
          <section className={cn(activeTab === "snapshot" ? "block" : "hidden", "xl:col-start-2 xl:row-start-3 xl:mt-4 xl:block")}>
            {coverage}
          </section>
        </aside>
      </div>
    </div>
  );
}

export { RepresentativeQuotes as HkRepresentativePanel };
