/**
 * 美股市场页
 * 路由：/markets/us
 * 板块：指数条 / 个股榜单 / 宏观速览 / 国债 / 大宗 / 新闻
 */
import { Suspense } from "react";
import { MarketOverview } from "@/components/market-overview";
import { MoversBoard, TopNews } from "@/components/movers-board";
import { MacroSnapshot } from "@/components/macro-snapshot";
import { TreasuryBoard } from "@/components/treasury-board";
import { CommoditiesBoard } from "@/components/commodities-board";
import { StockSearch } from "@/components/stock-search";
import { DatePicker } from "@/components/date-picker";
import { RefreshButton } from "@/components/refresh-button";
import { MarketStatusBar } from "@/components/market-status-bar";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";

function CardSkeleton() {
  return <Skeleton className="h-40 w-full rounded-lg" />;
}

export default async function UsMarketPage({
  searchParams,
}: {
  searchParams: Promise<{ date?: string }>;
}) {
  const { date } = await searchParams;

  return (
    <div className="space-y-6 px-4 lg:px-6">
      {/* 顶部操作栏 */}
      <div className="flex items-center gap-3">
        <h1 className="text-lg font-semibold">美股</h1>
        <StockSearch />
        <DatePicker />
        <RefreshButton />
        {/* 市场状态带：本市场开闭市状态 + 倒计时 + 数据日期（ml-auto 靠右） */}
        <Suspense fallback={null}>
          <MarketStatusBar market="US" />
        </Suspense>
        {date && (
          <Badge variant="secondary" className="bg-accent/20 text-accent">
            快照模式：{date}
          </Badge>
        )}
      </div>

      {/* 美股指数 */}
      <Suspense fallback={<Skeleton className="h-24 w-full rounded-lg" />}>
        <MarketOverview market="us" />
      </Suspense>

      {/* 个股榜单 */}
      <Suspense
        key={`movers-${date ?? ""}`}
        fallback={<CardSkeleton />}
      >
        <MoversBoard market="us" date={date} />
      </Suspense>

      {/* 宏观三卡 */}
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <Suspense fallback={<CardSkeleton />}>
          <MacroSnapshot />
        </Suspense>
        <Suspense fallback={<CardSkeleton />}>
          <TreasuryBoard />
        </Suspense>
        <Suspense fallback={<CardSkeleton />}>
          <CommoditiesBoard />
        </Suspense>
      </div>

      {/* 新闻 */}
      <Suspense fallback={<CardSkeleton />}>
        <TopNews market="us" />
      </Suspense>
    </div>
  );
}
