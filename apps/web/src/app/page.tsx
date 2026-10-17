/**
 * 首页看板（Phase B —— 三市均衡投研首页）
 * 信息架构（§3 目标 IA）：
 *   命令栏: DashboardToolbar（搜索 · 日期 · 刷新 · 市场状态 · 快照Badge）
 *   DataSyncStatus
 *   Band1 市场情绪总览: MarketSentimentBoard（三卡 CN/US/HK）
 *   Band1.5 自选股条: WatchlistStrip（client）
 *   Band2 大盘指数（分市场分组）: IndicesByMarket
 *   主区(2fr) + 侧栏(~20rem):
 *     主区 Band3 三市深度: MarketDeepSection（URL ?dmkt= 切 CN/US/HK）
 *     侧栏 ContextSidebar：事件中心 + 本周重点 + 热门资讯
 *   Band5 底部满宽指标带: MarketMetricsBand（宏观·大宗·国债）
 * 各块独立 Suspense + 骨架；Band1/Band3 用 key 便于快照/切市刷新。
 */
import { Suspense } from "react";
import { DashboardToolbar } from "@/components/dashboard/dashboard-toolbar";
import { DataSyncStatus } from "@/components/data-sync-status";
import { MarketSentimentBoard } from "@/components/market-sentiment-board";
import { WatchlistStrip } from "@/components/watchlist-strip";
import { IndicesByMarket } from "@/components/indices-by-market";
import { MarketDeepSection } from "@/components/market-deep-section";
import { ContextSidebar } from "@/components/dashboard/context-sidebar";
import { MarketMetricsBand } from "@/components/market-metrics-band";
import { Skeleton } from "@/components/ui/skeleton";

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
    <div className="mx-auto flex w-full max-w-[76rem] flex-col gap-4 px-4 md:gap-6 lg:px-6">
      <DashboardToolbar date={date} />

      {/* 数据同步状态（全量初始化/每日更新进度） */}
      <DataSyncStatus className="px-0 lg:px-0" />

      {/* Band1 市场情绪总览：三卡 CN/US/HK */}
      <section>
        <Suspense
          key={`sentiment-${date ?? ""}`}
          fallback={
            <Skeleton className="h-[532px] w-full rounded-lg md:h-[354px] xl:h-[190px]" />
          }
        >
          <MarketSentimentBoard date={date} />
        </Suspense>
      </section>

      {/* Band1.5 自选股条（client） */}
      <section>
        <Suspense fallback={<Skeleton className="h-12 w-full rounded-lg" />}>
          <WatchlistStrip />
        </Suspense>
      </section>

      {/* Band2 大盘指数（分市场分组） */}
      <section>
        <h2 className="mb-3 text-sm font-medium text-fg-dim">大盘指数</h2>
        <Suspense
          fallback={
            <Skeleton className="h-[300px] w-full rounded-lg md:h-[208px] xl:h-[118px]" />
          }
        >
          <IndicesByMarket />
        </Suspense>
      </section>

      {/* 主+侧布局：主区三市深度 · 侧栏资讯/事件/日历 */}
      <div className="grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,2fr)_20rem]">
        {/* 主区 Band3 三市深度（URL ?dmkt= 切市） */}
        <div className="space-y-6">
          <Suspense
            key={`deep-${market}-${date ?? ""}`}
            fallback={<CardSkeleton />}
          >
            <MarketDeepSection date={date} market={market} />
          </Suspense>
        </div>

        {/* 侧栏：事件中心 + 本周重点 + 热门资讯 */}
        <Suspense
          fallback={<Skeleton className="h-[43.75rem] w-full rounded-lg" />}
        >
          <ContextSidebar />
        </Suspense>
      </div>

      {/* Band5 底部满宽指标带：宏观 · 大宗 · 国债 */}
      <section>
        <Suspense
          fallback={
            <Skeleton className="h-[395px] w-full rounded-xl xl:h-[137px]" />
          }
        >
          <MarketMetricsBand />
        </Suspense>
      </section>
    </div>
  );
}
