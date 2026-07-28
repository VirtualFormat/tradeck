/**
 * 首页看板（8 个板块独立 Suspense + 市场切换）
 * 布局套用 shadcn dashboard-01 block 的 main content 结构
 */
import { Suspense } from "react";
import { MarketOverview } from "@/components/market-overview";
import { StockSearch } from "@/components/stock-search";
import { MoversBoard, TopNews } from "@/components/movers-board";
import { MacroSnapshot } from "@/components/macro-snapshot";
import { CommoditiesBoard } from "@/components/commodities-board";
import { TreasuryBoard } from "@/components/treasury-board";
import { MarketCompareCards } from "@/components/market-compare-cards";
import { DatePicker } from "@/components/date-picker";
import { RefreshButton } from "@/components/refresh-button";
import { DataSyncStatus } from "@/components/data-sync-status";
import { MarketStatusBar } from "@/components/market-status-bar";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";

function CardSkeleton({ title }: { title: string }) {
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
  searchParams: Promise<{ date?: string }>;
}) {
  const { date } = await searchParams;

  return (
    <>
      {/* 顶部操作栏：搜索 + 日期回看 + 刷新 */}
      <div className="flex items-center gap-3 px-4 lg:px-6">
        <StockSearch />
        <DatePicker />
        <RefreshButton />
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

      {/* 数据同步状态（全量初始化/每日更新进度） */}
      <DataSyncStatus />

      {/* 大盘指数（全球） */}
      <section className="px-4 lg:px-6">
        <h2 className="mb-3 text-sm font-medium text-fg-dim">大盘指数</h2>
        <Suspense fallback={<Skeleton className="h-24 w-full rounded-lg" />}>
          <MarketOverview market="global" />
        </Suspense>
      </section>

      {/* 三市对比总览（指数卡下、涨跌四榜上） */}
      <section className="px-4 lg:px-6">
        <Suspense
          key={`compare-${date ?? ""}`}
          fallback={<Skeleton className="h-64 w-full rounded-lg" />}
        >
          <MarketCompareCards date={date} />
        </Suspense>
      </section>

      {/* 主+侧布局 */}
      <div className="grid grid-cols-1 gap-6 px-4 lg:grid-cols-[1fr_20rem] lg:px-6">
        {/* 主区 */}
        <div className="space-y-6">
          <Suspense
            key={`movers-${date ?? ""}`}
            fallback={<CardSkeleton title="涨跌榜" />}
          >
            <MoversBoard market="global" date={date} />
          </Suspense>

          <Suspense fallback={<CardSkeleton title="热门资讯" />}>
            <TopNews market="global" />
          </Suspense>
        </div>

        {/* 侧栏（全球概览固定三卡） */}
        <div className="space-y-6">
          <Suspense fallback={<CardSkeleton title="宏观速览" />}>
            <MacroSnapshot />
          </Suspense>
          <Suspense fallback={<CardSkeleton title="大宗商品" />}>
            <CommoditiesBoard />
          </Suspense>
          <Suspense fallback={<CardSkeleton title="国债收益率" />}>
            <TreasuryBoard />
          </Suspense>
        </div>
      </div>
    </>
  );
}
