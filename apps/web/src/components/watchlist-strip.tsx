/**
 * 首页紧凑自选股条。
 * localStorage 结构及浏览器侧 Next API 报价逻辑与筛选页保持一致。
 */
"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { CaretRightIcon } from "@phosphor-icons/react";

import { EmptyState } from "@/components/empty-state";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import {
  fetchValidQuotes,
  parseWatchlist,
  reconcileWatchlist,
  validateWatchlistSymbols,
  WATCHLIST_KEY,
} from "@/lib/watchlist";

interface QuoteItem {
  symbol: string;
  change_percent: number | null;
}

function fmtPct(fraction: number | null | undefined): string {
  if (fraction == null) return "—";
  const sign = fraction > 0 ? "+" : "";
  return `${sign}${(fraction * 100).toFixed(2)}%`;
}

export function WatchlistStrip() {
  const [watchlist, setWatchlist] = useState<string[]>([]);
  const [quotes, setQuotes] = useState<Record<string, number | null>>({});

  useEffect(() => {
    const saved = localStorage.getItem(WATCHLIST_KEY);
    if (!saved) return;

    const list = parseWatchlist(saved);
    // localStorage 只能在挂载后读取，避免服务端与客户端首屏不一致。
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setWatchlist(list);
  }, []);

  useEffect(() => {
    if (watchlist.length === 0) return;

    let cancelled = false;
    validateWatchlistSymbols(watchlist)
      .then(async (validSymbols) => {
        if (cancelled) return;
        const cleaned = reconcileWatchlist(watchlist, validSymbols);
        if (cleaned.length !== watchlist.length) {
          localStorage.setItem(WATCHLIST_KEY, JSON.stringify(cleaned));
          setWatchlist(cleaned);
        }
        const data = await fetchValidQuotes<QuoteItem>(cleaned);
        if (cancelled) return;
        const map: Record<string, number | null> = {};
        for (const item of data) {
          if (item?.symbol) map[item.symbol] = item.change_percent ?? null;
        }
        setQuotes(map);
      })
      .catch(() => {
        if (!cancelled) setQuotes({});
      });

    return () => {
      cancelled = true;
    };
  }, [watchlist]);

  return (
    <Card
      size="sm"
      className="h-11 min-w-0 flex-row items-center gap-3 px-3.5 py-0"
    >
      <Link
        href="/screener"
        className="flex shrink-0 items-center gap-1 text-xs font-medium text-fg-dim transition-colors hover:text-foreground"
      >
        自选股 · 实时
        <CaretRightIcon className="size-3" weight="bold" />
      </Link>

      {watchlist.length === 0 ? (
        <EmptyState
          compact
          inline
          title="还没有自选标的，去筛选器添加"
          className="min-w-0 flex-1 truncate"
        />
      ) : (
        <div className="flex min-w-0 flex-1 items-center gap-4 overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
          {watchlist.map((symbol) => {
            const pct = symbol in quotes ? quotes[symbol] : undefined;
            const hasPct = pct != null;
            const pctClass =
              pct == null || pct === 0
                ? "text-muted-foreground"
                : pct > 0
                  ? "text-up"
                  : "text-down";

            return (
              <Link
                key={symbol}
                href={`/stocks/${symbol}`}
                className="flex shrink-0 items-center gap-1.5 whitespace-nowrap text-xs transition-opacity hover:opacity-75"
              >
                <span className="font-medium text-foreground">{symbol}</span>
                {hasPct ? (
                  <span className={cn("tabular-nums", pctClass)}>
                    {fmtPct(pct)}
                  </span>
                ) : null}
              </Link>
            );
          })}
        </div>
      )}

      <Link
        href="/screener"
        className="ml-auto shrink-0 border-l border-border pl-3 text-[11px] text-muted-foreground transition-colors hover:text-foreground"
      >
        管理
      </Link>
    </Card>
  );
}
