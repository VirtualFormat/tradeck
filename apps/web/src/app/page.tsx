/**
 * 首页看板（8 个板块独立 Suspense，先加载完的先显示）
 */
import { Suspense } from "react";
import { MarketOverview } from "@/components/market-overview";
import { StockSearch } from "@/components/stock-search";
import { PageHeader } from "@/components/page-header";
import { MoversBoard, TopNews } from "@/components/movers-board";
import { MacroSnapshot } from "@/components/macro-snapshot";
import { CommoditiesBoard } from "@/components/commodities-board";
import { TreasuryBoard } from "@/components/treasury-board";
import { Skeleton } from "@/components/ui/skeleton";

function CardSkeleton({ title }: { title: string }) {
  return (
    <div>
      <Skeleton className="mb-2 h-4 w-24" />
      <Skeleton className="h-40 w-full rounded-lg" />
    </div>
  );
}

export default function Home() {
  return (
    <>
      <PageHeader
        title="看板"
        subtitle="Market Dashboard · Global"
        right={<StockSearch />}
      />

      {/* 大盘指数（独立 Suspense） */}
      <section className="mb-6">
        <h2 className="mb-3 text-sm font-medium text-fg-dim">大盘指数</h2>
        <Suspense fallback={<Skeleton className="h-24 w-full rounded-lg" />}>
          {/* @ts-expect-error Server Component */}
          <MarketOverview />
        </Suspense>
      </section>

      {/* 主+侧布局 */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1fr_18rem]">
        {/* 主区 */}
        <div className="space-y-6">
          <Suspense fallback={<CardSkeleton title="涨跌榜" />}>
            {/* @ts-expect-error Server Component */}
            <MoversBoard />
          </Suspense>
          <Suspense fallback={<CardSkeleton title="热门资讯" />}>
            {/* @ts-expect-error Server Component */}
            <TopNews />
          </Suspense>
        </div>

        {/* 侧栏 */}
        <div className="space-y-6">
          <Suspense fallback={<CardSkeleton title="宏观速览" />}>
            {/* @ts-expect-error Server Component */}
            <MacroSnapshot />
          </Suspense>
          <Suspense fallback={<CardSkeleton title="大宗商品" />}>
            {/* @ts-expect-error Server Component */}
            <CommoditiesBoard />
          </Suspense>
          <Suspense fallback={<CardSkeleton title="国债收益率" />}>
            {/* @ts-expect-error Server Component */}
            <TreasuryBoard />
          </Suspense>
        </div>
      </div>
    </>
  );
}
