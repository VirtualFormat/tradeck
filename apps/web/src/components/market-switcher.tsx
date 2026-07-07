/**
 * 市场切换器（客户端组件）
 * 通过 URL search params 切换市场
 */
"use client";

import { useRouter, usePathname, useSearchParams } from "next/navigation";
import { useCallback } from "react";

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
    <div className="flex items-center gap-1 rounded-md border border-border bg-panel-2 p-0.5">
      {MARKETS.map((m) => (
        <button
          key={m.key}
          onClick={() => handleSwitch(m.key)}
          className={`rounded-sm px-2.5 py-1 text-[11px] font-medium transition-colors ${
            current === m.key
              ? "bg-accent text-white"
              : "text-muted hover:text-fg"
          }`}
        >
          {m.label}
        </button>
      ))}
    </div>
  );
}

export function getMarketFromParams(
  searchParams: { market?: string }
): Market {
  return (searchParams.market as Market) ?? "global";
}
