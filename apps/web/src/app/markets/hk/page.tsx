import { Suspense } from "react";

import { HkMarketV3 } from "@/components/markets-v3/hk-market-v3";
import { MarketIndexStrip } from "@/components/markets-v3/market-index-strip";
import { MarketPageShell } from "@/components/markets-v3/market-page-shell";
import { MarketPageToolbar } from "@/components/markets-v3/market-page-toolbar";
import { Skeleton } from "@/components/ui/skeleton";

export const dynamic = "force-dynamic";

const HK_INDICES = [
  { symbol: "^HSI", name: "恒生指数" },
  { symbol: "^HSCEI", name: "恒生国企" },
  { symbol: "^HSTECH", name: "恒生科技" },
];

export default async function HkMarketPage({
  searchParams,
}: {
  searchParams: Promise<{ date?: string }>;
}) {
  const { date } = await searchParams;

  return (
    <MarketPageShell
      toolbar={
        <MarketPageToolbar
          market="HK"
          title="港股市场"
          subtitle="指数与代表标的 · 数据覆盖 · 港股资讯"
          date={date}
        />
      }
      indices={
        <Suspense fallback={<Skeleton className="h-24 w-full rounded-xl" />}>
          <MarketIndexStrip indices={HK_INDICES} date={date} />
        </Suspense>
      }
    >
      <Suspense
        key={`hk-v3-${date ?? ""}`}
        fallback={<Skeleton className="h-[34rem] w-full rounded-xl" />}
      >
        <HkMarketV3 date={date} />
      </Suspense>
    </MarketPageShell>
  );
}
