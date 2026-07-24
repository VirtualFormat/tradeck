/**
 * 全球宏观页
 * 路由：/global
 * 板块：跨资产总览 / 美债收益率曲线 / 市场内部结构
 */
import { Suspense } from "react";
import { CrossAssetMatrix } from "@/components/cross-asset-matrix";
import { YieldCurvePanel } from "@/components/yield-curve-panel";
import { RelativeStrengthCards } from "@/components/relative-strength-cards";
import { StockSearch } from "@/components/stock-search";
import { RefreshButton } from "@/components/refresh-button";
import { Skeleton } from "@/components/ui/skeleton";

// 强制动态渲染：每次请求实时从 backend 取数（行情数据有时效性）
export const dynamic = "force-dynamic";

function CardSkeleton() {
  return <Skeleton className="h-40 w-full rounded-lg" />;
}

export default function GlobalMacroPage() {
  return (
    <div className="space-y-6 px-4 lg:px-6">
      {/* 顶部操作栏 */}
      <div className="flex items-center gap-3">
        <h1 className="text-lg font-semibold">全球宏观</h1>
        <StockSearch />
        <RefreshButton />
      </div>

      {/* 跨资产总览 */}
      <Suspense fallback={<Skeleton className="h-[420px] w-full rounded-lg" />}>
        <CrossAssetMatrix />
      </Suspense>

      {/* 美债收益率曲线 */}
      <Suspense fallback={<Skeleton className="h-[520px] w-full rounded-lg" />}>
        <YieldCurvePanel />
      </Suspense>

      {/* 市场内部结构 */}
      <section>
        <div className="mb-3 flex items-center gap-3">
          <h2 className="text-sm font-medium text-fg-dim">市场内部结构</h2>
        </div>
        <Suspense fallback={<CardSkeleton />}>
          <RelativeStrengthCards />
        </Suspense>
      </section>
    </div>
  );
}
