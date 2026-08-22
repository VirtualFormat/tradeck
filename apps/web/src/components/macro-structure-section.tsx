/** 宏观工作区：市场结构视图（跨资产 / 收益率曲线 / 相对强弱）。 */
import { Suspense } from "react";

import { CrossAssetMatrix } from "@/components/cross-asset-matrix";
import { RelativeStrengthCards } from "@/components/relative-strength-cards";
import { YieldCurvePanel } from "@/components/yield-curve-panel";
import { Skeleton } from "@/components/ui/skeleton";

function CardSkeleton() {
  return <Skeleton className="h-40 w-full rounded-lg" />;
}

export function MacroStructureSection() {
  return (
    <div className="space-y-6">
      <Suspense fallback={<Skeleton className="h-[420px] w-full rounded-lg" />}>
        <CrossAssetMatrix />
      </Suspense>

      <Suspense fallback={<Skeleton className="h-[520px] w-full rounded-lg" />}>
        <YieldCurvePanel />
      </Suspense>

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
