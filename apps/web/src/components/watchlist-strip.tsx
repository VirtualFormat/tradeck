/**
 * 自选股条（Band1.5）
 * - client 组件：从 localStorage 读自选股（与 /screener 同一 key/结构）
 * - 横向 chip 条：代码 + 涨跌%（涨跌上色，红涨绿跌）
 * - 客户端 fetch /api/quotes?symbols=... 取行情；取不到就只显代码（优雅降级）
 * - 右侧「管理」链到 /screener；空列表显一行引导文案
 */
"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { Card } from "@/components/ui/card";
import { StarIcon } from "@phosphor-icons/react";
import { cn } from "@/lib/utils";

const WATCHLIST_KEY = "tradeck-watchlist";

/** 与 /screener 的批量报价返回结构一致 */
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
  // 代码 → 涨跌% 的映射；取不到时该代码无条目 → 只显代码
  const [quotes, setQuotes] = useState<Record<string, number | null>>({});

  // 读自选股（与 /screener 同一 key）
  useEffect(() => {
    const saved = localStorage.getItem(WATCHLIST_KEY);
    if (!saved) return;
    try {
      const list = JSON.parse(saved);
      // 挂载后一次性读取；在 effect 内 setState 是为避免 SSR/hydration 不匹配（客户端才有 localStorage）
      // eslint-disable-next-line react-hooks/set-state-in-effect
      if (Array.isArray(list)) setWatchlist(list.filter((s) => typeof s === "string"));
    } catch {
      // ignore
    }
  }, []);

  // 拉行情（客户端）；失败 → 保持空 quotes，chip 只显代码
  useEffect(() => {
    // 空列表：无需拉行情（空态分支不读 quotes，保留旧值也不渲染）
    if (watchlist.length === 0) return;
    let cancelled = false;
    fetch(`/api/quotes?symbols=${watchlist.join(",")}&_t=${Date.now()}`)
      .then((r) => r.json())
      .then((data: QuoteItem[]) => {
        if (cancelled || !Array.isArray(data)) return;
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
      className="@container/card flex-row items-center gap-3 bg-linear-to-t from-primary/5 to-card px-3 py-2.5 shadow-xs dark:bg-card"
    >
      <div className="flex shrink-0 items-center gap-1.5 text-fg-dim">
        <StarIcon className="h-4 w-4" weight="fill" />
        <span className="text-sm font-medium">自选</span>
      </div>

      {watchlist.length === 0 ? (
        <p className="flex-1 text-xs text-muted-foreground">
          暂无自选股，去
          <Link href="/screener" className="mx-1 text-foreground underline-offset-2 hover:underline">
            筛选器
          </Link>
          添加关注标的。
        </p>
      ) : (
        <div className="flex flex-1 flex-wrap items-center gap-2 overflow-hidden">
          {watchlist.map((symbol) => {
            const pct = symbol in quotes ? quotes[symbol] : undefined;
            const hasPct = pct != null;
            const up = (pct ?? 0) >= 0;
            return (
              <Link
                key={symbol}
                href={`/stocks/${symbol}`}
                className="flex items-center gap-1.5 rounded-md bg-secondary px-2 py-1 text-xs transition-colors hover:bg-secondary/70"
              >
                <span className="font-medium text-foreground">{symbol}</span>
                {hasPct && (
                  <span className={cn("tabular-nums", up ? "text-up" : "text-down")}>
                    {fmtPct(pct)}
                  </span>
                )}
              </Link>
            );
          })}
        </div>
      )}

      <Link
        href="/screener"
        className="ml-auto shrink-0 text-xs text-muted-foreground transition-colors hover:text-foreground"
      >
        管理
      </Link>
    </Card>
  );
}
