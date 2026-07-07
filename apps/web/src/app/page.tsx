/**
 * 首页看板（8 个板块独立 Suspense + 市场切换）
 */
import { Suspense } from "react";
import { MarketOverview } from "@/components/market-overview";
import { StockSearch } from "@/components/stock-search";
import { PageHeader } from "@/components/page-header";
import { MoversBoard, TopNews } from "@/components/movers-board";
import { MacroSnapshot } from "@/components/macro-snapshot";
import { CommoditiesBoard } from "@/components/commodities-board";
import { TreasuryBoard } from "@/components/treasury-board";
import { MarketSwitcher } from "@/components/market-switcher";
import { Skeleton } from "@/components/ui/skeleton";

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
  searchParams: Promise<{ market?: string }>;
}) {
  const { market: marketParam } = await searchParams;
  const market = marketParam ?? "global";

  return (
    <>
      <PageHeader
        title="看板"
        subtitle="Market Dashboard · Global"
        right={
          <div className="flex items-center gap-3">
            <MarketSwitcher />
            <StockSearch />
          </div>
        }
      />

      {/* 大盘指数（按市场过滤） */}
      <section className="mb-6">
        <h2 className="mb-3 text-sm font-medium text-fg-dim">
          大盘指数
          {market !== "global" && (
            <span className="ml-2 text-[10px] text-muted">
              {market === "us" ? "美股" : market === "cn" ? "A股" : "港股"}
            </span>
          )}
        </h2>
        <Suspense key={`indices-${market}`} fallback={<Skeleton className="h-24 w-full rounded-lg" />}>
          {/* @ts-expect-error Server Component */}
          <MarketOverview market={market} />
        </Suspense>
      </section>

      {/* 主+侧布局 */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1fr_18rem]">
        {/* 主区 */}
        <div className="space-y-6">
          <Suspense key={`movers-${market}`} fallback={<CardSkeleton title="涨跌榜" />}>
            {/* @ts-expect-error Server Component */}
            <MoversBoard market={market} />
          </Suspense>
          <Suspense key={`news-${market}`} fallback={<CardSkeleton title="热门资讯" />}>
            {/* @ts-expect-error Server Component */}
            <TopNews market={market} />
          </Suspense>
        </div>

        {/* 侧栏（全球/美股显示，A 股/港股只显示大宗+国债） */}
        <div className="space-y-6">
          {(market === "global" || market === "us") && (
            <Suspense fallback={<CardSkeleton title="宏观速览" />}>
              {/* @ts-expect-error Server Component */}
              <MacroSnapshot />
            </Suspense>
          )}
          {(market === "global" || market === "us" || market === "hk") && (
            <Suspense fallback={<CardSkeleton title="大宗商品" />}>
              {/* @ts-expect-error Server Component */}
              <CommoditiesBoard />
            </Suspense>
          )}
          {(market === "global" || market === "us") && (
            <Suspense fallback={<CardSkeleton title="国债收益率" />}>
              {/* @ts-expect-error Server Component */}
              <TreasuryBoard />
            </Suspense>
          )}
        </div>
      </div>
    </>
  );
}
