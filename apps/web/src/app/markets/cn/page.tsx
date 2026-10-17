import { Suspense } from "react";

import { CnMarketV3 } from "@/components/markets-v3/cn-market-v3";
import { MarketIndexStrip } from "@/components/markets-v3/market-index-strip";
import { MarketPageShell } from "@/components/markets-v3/market-page-shell";
import { MarketPageToolbar } from "@/components/markets-v3/market-page-toolbar";
import { Skeleton } from "@/components/ui/skeleton";

const CN_INDICES = [
  { symbol: "000001.SS", name: "上证指数" },
  { symbol: "399001.SZ", name: "深证成指" },
  { symbol: "399006.SZ", name: "创业板指" },
];

export default async function CnMarketPage({
  searchParams,
}: {
  searchParams: Promise<{ date?: string }>;
}) {
  const { date } = await searchParams;

  return (
    <MarketPageShell
      toolbar={
        <MarketPageToolbar
          market="CN"
          title="A股市场"
          subtitle="全市场宽度 · 行业轮动 · 资金与公司事件"
          date={date}
        />
      }
      indices={
        <Suspense fallback={<Skeleton className="h-24 w-full rounded-xl" />}>
          <MarketIndexStrip indices={CN_INDICES} date={date} />
        </Suspense>
      }
    >
      <Suspense
        key={`cn-v3-${date ?? ""}`}
        fallback={<Skeleton className="h-[42rem] w-full rounded-xl" />}
      >
        <CnMarketV3 date={date} />
      </Suspense>
    </MarketPageShell>
  );
}
