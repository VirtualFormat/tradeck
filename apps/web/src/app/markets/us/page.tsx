import { Suspense } from "react";

import { MarketIndexStrip } from "@/components/markets-v3/market-index-strip";
import { MarketPageShell } from "@/components/markets-v3/market-page-shell";
import { MarketPageToolbar } from "@/components/markets-v3/market-page-toolbar";
import { UsMarketV3 } from "@/components/markets-v3/us-market-v3";
import { Skeleton } from "@/components/ui/skeleton";

const US_INDICES = [
  { symbol: "^GSPC", name: "标普500" },
  { symbol: "^IXIC", name: "纳斯达克" },
  { symbol: "^DJI", name: "道琼斯" },
];

export default async function UsMarketPage({
  searchParams,
}: {
  searchParams: Promise<{ date?: string }>;
}) {
  const { date } = await searchParams;

  return (
    <MarketPageShell
      toolbar={
        <MarketPageToolbar
          market="US"
          title="美股市场"
          subtitle="市场内部结构 · 财报事件 · 跨资产联动"
          date={date}
        />
      }
      indices={
        <Suspense fallback={<Skeleton className="h-24 w-full rounded-xl" />}>
          <MarketIndexStrip indices={US_INDICES} date={date} />
        </Suspense>
      }
    >
      <Suspense
        key={`us-v3-${date ?? ""}`}
        fallback={<Skeleton className="h-[38rem] w-full rounded-xl" />}
      >
        <UsMarketV3 date={date} />
      </Suspense>
    </MarketPageShell>
  );
}
