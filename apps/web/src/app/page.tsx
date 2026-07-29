/**
 * 首页看板（Phase B —— 三市均衡投研首页）
 * 信息架构（§3 目标 IA）：
 *   命令栏: StockSearch · DatePicker · RefreshButton · ThemeToggle · (spacer) · MarketStatusBar · 快照Badge
 *   DataSyncStatus
 *   Band1 市场情绪总览: MarketSentimentBoard（三卡 CN/US/HK）
 *   Band1.5 自选股条: WatchlistStrip（client）
 *   Band2 大盘指数（分市场分组）: IndicesByMarket
 *   主区(2fr) + 侧栏(~20rem):
 *     主区 Band3 三市深度: MarketDeepSection（URL ?dmkt= 切 CN/US/HK）
 *     侧栏 竖排: TodayEvents + EconCalendarWeek + TopNews
 *   Band5 底部满宽指标带: MarketMetricsBand（宏观·大宗·国债）
 * 各块独立 Suspense + 骨架；Band1/Band3 用 key 便于快照/切市刷新。
 */
import { Suspense } from "react";
import { StockSearch } from "@/components/stock-search";
import { DatePicker } from "@/components/date-picker";
import { RefreshButton } from "@/components/refresh-button";
import { ThemeToggle } from "@/components/theme-toggle";
import { DataSyncStatus } from "@/components/data-sync-status";
import { MarketStatusBar } from "@/components/market-status-bar";
import { MarketSentimentBoard } from "@/components/market-sentiment-board";
import { WatchlistStrip } from "@/components/watchlist-strip";
import { IndicesByMarket } from "@/components/indices-by-market";
import { MarketDeepSection } from "@/components/market-deep-section";
import { TodayEvents } from "@/components/today-events";
import { EconCalendarWeek } from "@/components/econ-calendar-week";
import { MarketMetricsBand } from "@/components/market-metrics-band";
import { TopNews } from "@/components/movers-board";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";

function CardSkeleton() {
  return (
    <div>
      <Skeleton className="mb-2 h-4 w-24" />
      <Skeleton className="h-40 w-full rounded-lg" />
    </div>
  );
}

export default async function Home({
  searchParams,
}: {
  searchParams: Promise<{ date?: string; dmkt?: string }>;
}) {
  const { date, dmkt } = await searchParams;
  const market: "cn" | "us" | "hk" =
    dmkt === "us" || dmkt === "hk" ? dmkt : "cn";

  return (
    <>
      {/* 命令栏：搜索 · 日期回看 · 刷新 · 主题切换 · (spacer) · 市场状态带 · 快照Badge */}
      <div className="flex items-center gap-3 px-4 lg:px-6">
        <StockSearch />
        <DatePicker />
        <RefreshButton />
        <ThemeToggle />
        <div className="ml-auto flex items-center gap-3">
          {/* 市场状态带：三市开闭市状态 + 数据日期 + 倒计时 */}
          <Suspense fallback={null}>
            <MarketStatusBar />
          </Suspense>
          {date && (
            <Badge variant="secondary" className="bg-accent/20 text-accent">
              快照模式：{date}
            </Badge>
          )}
        </div>
      </div>

      {/* 数据同步状态（全量初始化/每日更新进度） */}
      <DataSyncStatus />

      {/* Band1 市场情绪总览：三卡 CN/US/HK */}
      <section className="px-4 lg:px-6">
        <Suspense
          key={`sentiment-${date ?? ""}`}
          fallback={<Skeleton className="h-64 w-full rounded-lg" />}
        >
          <MarketSentimentBoard date={date} />
        </Suspense>
      </section>

      {/* Band1.5 自选股条（client） */}
      <section className="px-4 lg:px-6">
        <Suspense fallback={<Skeleton className="h-12 w-full rounded-lg" />}>
          <WatchlistStrip />
        </Suspense>
      </section>

      {/* Band2 大盘指数（分市场分组） */}
      <section className="px-4 lg:px-6">
        <h2 className="mb-3 text-sm font-medium text-fg-dim">大盘指数</h2>
        <Suspense fallback={<Skeleton className="h-40 w-full rounded-lg" />}>
          <IndicesByMarket />
        </Suspense>
      </section>

      {/* 主+侧布局：主区三市深度 · 侧栏资讯/事件/日历 */}
      <div className="grid grid-cols-1 gap-6 px-4 lg:grid-cols-[2fr_20rem] lg:px-6">
        {/* 主区 Band3 三市深度（URL ?dmkt= 切市） */}
        <div className="space-y-6">
          <Suspense
            key={`deep-${market}-${date ?? ""}`}
            fallback={<CardSkeleton />}
          >
            <MarketDeepSection date={date} market={market} />
          </Suspense>
        </div>

        {/* 侧栏：今日事件 + 本周经济日历 + 热门资讯 */}
        <div className="space-y-6">
          <Suspense fallback={<CardSkeleton />}>
            <TodayEvents />
          </Suspense>
          <Suspense fallback={<CardSkeleton />}>
            <EconCalendarWeek />
          </Suspense>
          <Suspense fallback={<CardSkeleton />}>
            <TopNews market="global" />
          </Suspense>
        </div>
      </div>

      {/* Band5 底部满宽指标带：宏观 · 大宗 · 国债 */}
      <section className="px-4 lg:px-6">
        <Suspense fallback={<Skeleton className="h-48 w-full rounded-lg" />}>
          <MarketMetricsBand />
        </Suspense>
      </section>
    </>
  );
}
