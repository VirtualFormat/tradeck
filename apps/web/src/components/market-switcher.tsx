/**
 * 市场切换器（客户端组件）
 * 通过 URL search params 切换市场
 */
"use client";

import { useRouter, usePathname, useSearchParams } from "next/navigation";
import { useCallback } from "react";

import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";

export type Market = "global" | "us" | "cn" | "hk";

const MARKETS: { key: Market; label: string; short: string }[] = [
  { key: "global", label: "全球", short: "ALL" },
  { key: "us", label: "美股", short: "US" },
  { key: "cn", label: "A股", short: "CN" },
  { key: "hk", label: "港股", short: "HK" },
];

export function MarketSwitcher() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const current = (searchParams.get("market") as Market) ?? "global";

  const handleSwitch = useCallback(
    (market: Market) => {
      const params = new URLSearchParams(searchParams);
      if (market === "global") {
        params.delete("market");
      } else {
        params.set("market", market);
      }
      const query = params.toString();
      router.push(query ? `${pathname}?${query}` : pathname);
    },
    [router, pathname, searchParams]
  );

  return (
    <Tabs
      value={current}
      onValueChange={(v) => handleSwitch(v as Market)}
      className="flex-row gap-0"
    >
      <TabsList className="rounded-md border border-border bg-panel-2 p-0.5">
        {MARKETS.map((m) => (
          <TabsTrigger
            key={m.key}
            value={m.key}
            className="rounded-sm px-2.5 py-1 text-[11px] font-medium text-muted hover:text-fg data-active:bg-accent data-active:text-white"
          >
            {m.label}
          </TabsTrigger>
        ))}
      </TabsList>
    </Tabs>
  );
}

export function getMarketFromParams(
  searchParams: { market?: string }
): Market {
  return (searchParams.market as Market) ?? "global";
}
