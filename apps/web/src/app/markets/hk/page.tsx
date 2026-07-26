/**
 * 港股市场页（轻量）
 * 路由：/markets/hk
 * 板块：指数条 / 个股涨跌榜 / 新闻 / 数据覆盖说明
 */
import { Suspense } from "react";
import { MarketOverview } from "@/components/market-overview";
import { MoversBoard, TopNews } from "@/components/movers-board";
import { StockSearch } from "@/components/stock-search";
import { RefreshButton } from "@/components/refresh-button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

// 强制动态渲染：生产构建下不做静态预渲染，每次请求实时从 backend 取数
export const dynamic = "force-dynamic";

function CardSkeleton() {
  return <Skeleton className="h-40 w-full rounded-lg" />;
}

export default function HkMarketPage() {
  return (
    <div className="space-y-6 px-4 lg:px-6">
      {/* 顶部操作栏 */}
      <div className="flex items-center gap-3">
        <h1 className="text-lg font-semibold">港股</h1>
        <StockSearch />
        <RefreshButton />
      </div>

      {/* 港股指数 */}
      <Suspense fallback={<Skeleton className="h-24 w-full rounded-lg" />}>
        <MarketOverview market="hk" />
      </Suspense>

      {/* 个股涨跌榜（HK_STOCKS 报价） */}
      <Suspense fallback={<CardSkeleton />}>
        <MoversBoard market="hk" />
      </Suspense>

      {/* 数据覆盖说明 */}
      <Card>
        <CardContent className="py-3 text-[10px] text-muted-foreground">
          说明：港股目前仅覆盖 12 只代表性标的的报价快照，无免费涨跌榜/资金流/舆情数据源；后续接入券商行情（如富途 OpenAPI）后扩展。
        </CardContent>
      </Card>

      {/* 新闻 */}
      <Suspense fallback={<CardSkeleton />}>
        <TopNews market="hk" />
      </Suspense>
    </div>
  );
}
