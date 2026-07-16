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
import { MarketDistribution } from "@/components/market-distribution";
import { AdvanceDeclineBoard } from "@/components/advance-decline-board";
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
      {/* 顶部操作栏：市场切换 + 搜索 */}
      <div className="flex items-center gap-3 px-4 lg:px-6">
        <MarketSwitcher />
        <StockSearch />
      </div>

      {/* 大盘指数（按市场过滤） */}
      <section className="px-4 lg:px-6">
        <h2 className="mb-3 text-sm font-medium text-fg-dim">
          大盘指数
          {market !== "global" && (
            <span className="ml-2 text-[10px] text-muted">
              {market === "us" ? "美股" : market === "cn" ? "A股" : "港股"}
            </span>
          )}
        </h2>
        <Suspense
          key={`indices-${market}`}
          fallback={<Skeleton className="h-24 w-full rounded-lg" />}
        >
          <MarketOverview market={market} />
        </Suspense>
      </section>

      {/* 主+侧布局 */}
      <div className="grid grid-cols-1 gap-6 px-4 lg:grid-cols-[1fr_18rem] lg:px-6">
        {/* 主区 */}
        <div className="space-y-6">
          <Suspense
            key={`movers-${market}`}
            fallback={<CardSkeleton title="涨跌榜" />}
          >
            <MoversBoard market={market} />
          </Suspense>
          {/* 涨跌平 Donut（US/HK/CN 三市场） */}
          <Suspense fallback={<CardSkeleton title="涨跌平" />}>
            <AdvanceDeclineBoard />
          </Suspense>
          <Suspense
            key={`news-${market}`}
            fallback={<CardSkeleton title="热门资讯" />}
          >
            <TopNews market={market} />
          </Suspense>
        </div>

        {/* 侧栏（全球/美股显示，A 股/港股只显示大宗+国债） */}
        <div className="space-y-6">
          {market === "global" && (
            <Suspense fallback={<CardSkeleton title="市场分布" />}>
              <MarketDistribution />
            </Suspense>
          )}
          {(market === "global" || market === "us") && (
            <Suspense fallback={<CardSkeleton title="宏观速览" />}>
              <MacroSnapshot />
            </Suspense>
          )}
          {(market === "global" || market === "us" || market === "hk") && (
            <Suspense fallback={<CardSkeleton title="大宗商品" />}>
              <CommoditiesBoard />
            </Suspense>
          )}
          {(market === "global" || market === "us") && (
            <Suspense fallback={<CardSkeleton title="国债收益率" />}>
              <TreasuryBoard />
            </Suspense>
          )}
        </div>
      </div>
    </>
  );
}
