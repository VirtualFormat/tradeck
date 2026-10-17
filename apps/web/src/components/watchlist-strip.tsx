/**
 * 首页交易计划条：同步自选 v2 状态，并轮询浏览器侧报价代理。
 */
"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { CaretRightIcon } from "@phosphor-icons/react";

import { EmptyState } from "@/components/empty-state";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import {
  currencyPrefix,
  getQuoteFreshness,
  inferInstrumentIdentity,
} from "@/components/watchlist/types";
import { cn } from "@/lib/utils";
import {
  getWatchlistSymbols,
  migrateLegacyWatchlistStateAtomically,
  parseWatchlistState,
  serializeWatchlistState,
  WATCHLIST_CHANGE_EVENT,
  WATCHLIST_KEY,
  type WatchlistItem,
  type WatchlistState,
} from "@/lib/watchlist";

interface StripQuote {
  symbol: string;
  price: number | null;
  changePercent: number | null;
  dataAsOf: string | null;
  fetchedAt: string | null;
}

const QUOTE_REFRESH_MS = 30_000;
const FRESHNESS_TICK_MS = 60_000;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function finiteNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function nullableString(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}

function normalizeQuote(value: unknown): StripQuote | null {
  if (!isRecord(value) || typeof value.symbol !== "string") return null;
  const symbol = value.symbol.trim().toUpperCase();
  if (!symbol) return null;

  return {
    symbol,
    price: finiteNumber(value.last_price),
    changePercent: finiteNumber(value.change_percent),
    dataAsOf: nullableString(value.data_as_of),
    fetchedAt: nullableString(value.fetched_at),
  };
}

function readStoredState(): WatchlistState {
  try {
    return parseWatchlistState(window.localStorage.getItem(WATCHLIST_KEY));
  } catch {
    return parseWatchlistState(null);
  }
}

function isLegacyStoredWatchlist(value: string | null): boolean {
  if (value === null) return false;
  try {
    return Array.isArray(JSON.parse(value));
  } catch {
    return false;
  }
}

function formatPrice(
  value: number | null | undefined,
  prefix: string
): string {
  if (value == null) return "—";
  return `${prefix}${value.toLocaleString("zh-CN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

function formatChange(value: number | null | undefined): string {
  if (value == null) return "—";
  return `${value > 0 ? "+" : ""}${(value * 100).toFixed(2)}%`;
}

function getTriggeredAlerts(
  item: WatchlistItem,
  price: number | null
): { above: boolean; below: boolean } {
  if (price == null) return { above: false, below: false };
  const above = finiteNumber(item.alertAbove);
  const below = finiteNumber(item.alertBelow);
  return {
    above: above !== null && price >= above,
    below: below !== null && price <= below,
  };
}

function positionReturn(
  item: WatchlistItem,
  price: number | null
): number | null {
  const quantity = finiteNumber(item.quantity);
  const averageCost = finiteNumber(item.averageCost);
  if (
    quantity === null ||
    quantity <= 0 ||
    averageCost === null ||
    averageCost <= 0 ||
    price === null
  ) {
    return null;
  }

  const costBasis = quantity * averageCost;
  return ((quantity * price - costBasis) / costBasis) * 100;
}

export function WatchlistStrip() {
  const [watchlist, setWatchlist] = useState<WatchlistState>(() =>
    parseWatchlistState(null)
  );
  const [quotes, setQuotes] = useState<Record<string, StripQuote>>({});
  const [freshnessNow, setFreshnessNow] = useState<Date | null>(null);

  useEffect(() => {
    let active = true;
    let raw: string | null = null;
    try {
      raw = window.localStorage.getItem(WATCHLIST_KEY);
    } catch {
      // 存储不可用时仍维持当前页面的内存状态。
    }

    const initial = parseWatchlistState(raw);

    const handleWatchlistChange = (event: Event) => {
      const detail = (event as CustomEvent<WatchlistState | undefined>).detail;
      setWatchlist(
        detail
          ? parseWatchlistState(serializeWatchlistState(detail))
          : readStoredState()
      );
    };
    const handleStorage = (event: StorageEvent) => {
      if (event.key === null || event.key === WATCHLIST_KEY) {
        setWatchlist(readStoredState());
      }
    };

    window.addEventListener(WATCHLIST_CHANGE_EVENT, handleWatchlistChange);
    window.addEventListener("storage", handleStorage);

    const hydrate = async () => {
      let hydrated = initial;
      if (isLegacyStoredWatchlist(raw)) {
        try {
          hydrated = await migrateLegacyWatchlistStateAtomically(initial);
        } catch {
          // 迁移冲突或存储不可用时保留其他标签已经写入的最新状态。
          hydrated = readStoredState();
        }
      }
      if (active) setWatchlist(hydrated);
    };
    void hydrate();

    return () => {
      active = false;
      window.removeEventListener(WATCHLIST_CHANGE_EVENT, handleWatchlistChange);
      window.removeEventListener("storage", handleStorage);
    };
  }, []);

  useEffect(() => {
    const initialTick = window.setTimeout(() => {
      setFreshnessNow(new Date());
    }, 0);
    const interval = window.setInterval(() => {
      setFreshnessNow(new Date());
    }, FRESHNESS_TICK_MS);

    return () => {
      window.clearTimeout(initialTick);
      window.clearInterval(interval);
    };
  }, []);

  const symbols = useMemo(
    () => getWatchlistSymbols(watchlist),
    [watchlist]
  );
  const symbolKey = symbols.join(",");

  useEffect(() => {
    if (!symbolKey) return;

    let active = true;
    let controller: AbortController | null = null;

    const refreshQuotes = async () => {
      controller?.abort();
      const requestController = new AbortController();
      controller = requestController;

      try {
        const response = await fetch(
          `/api/quotes?symbols=${encodeURIComponent(symbolKey)}&_t=${Date.now()}`,
          { cache: "no-store", signal: requestController.signal }
        );
        if (!response.ok) return;
        const payload: unknown = await response.json();
        if (!active || controller !== requestController) return;

        const nextQuotes: Record<string, StripQuote> = {};
        if (Array.isArray(payload)) {
          for (const value of payload) {
            const quote = normalizeQuote(value);
            if (quote) nextQuotes[quote.symbol] = quote;
          }
        }
        setQuotes(nextQuotes);
      } catch (error) {
        if (!(error instanceof DOMException && error.name === "AbortError")) {
          // 短暂请求失败时保留上一次报价，下一轮继续刷新。
        }
      } finally {
        if (active && controller === requestController) {
          setFreshnessNow(new Date());
        }
      }
    };

    void refreshQuotes();
    const interval = window.setInterval(() => {
      void refreshQuotes();
    }, QUOTE_REFRESH_MS);

    return () => {
      active = false;
      window.clearInterval(interval);
      controller?.abort();
    };
  }, [symbolKey]);

  const groupedItems = useMemo(
    () =>
      [...watchlist.groups]
        .sort((left, right) => left.order - right.order)
        .map((group) => ({
          group,
          items: watchlist.items.filter((item) => item.groupId === group.id),
        }))
        .filter(({ items }) => items.length > 0),
    [watchlist]
  );

  return (
    <Card
      size="sm"
      className="min-h-12 min-w-0 flex-row items-stretch gap-0 px-3.5 py-0"
    >
      <Link
        href="/screener"
        className="flex shrink-0 items-center gap-1 pr-3 text-xs font-medium text-fg-dim transition-colors hover:text-foreground"
      >
        交易计划
        <CaretRightIcon className="size-3" weight="bold" />
      </Link>

      {watchlist.items.length === 0 ? (
        <EmptyState
          compact
          inline
          title="还没有自选标的，去筛选器添加"
          className="min-w-0 flex-1 self-center truncate"
        />
      ) : (
        <div className="flex min-w-0 flex-1 items-center gap-4 overflow-x-auto overscroll-x-contain py-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
          {groupedItems.map(({ group, items }, groupIndex) => (
            <div
              key={group.id}
              className={cn(
                "flex shrink-0 items-center gap-3",
                groupIndex > 0 && "border-l border-border pl-4"
              )}
            >
              <span className="text-[10px] font-medium text-muted-foreground">
                {group.name}
              </span>
              {items.map((item) => {
                const quote = quotes[item.symbol];
                const price = quote?.price ?? null;
                const change = quote?.changePercent ?? null;
                const freshness = getQuoteFreshness(
                  item.symbol,
                  quote?.dataAsOf ?? null,
                  freshnessNow ?? new Date(0)
                );
                const fetchedLabel = getQuoteFreshness(
                  item.symbol,
                  quote?.fetchedAt ?? null,
                  freshnessNow ?? new Date(0)
                ).localDateLabel;
                const isStale = quote != null && freshness.isStale;
                const triggeredAlerts = getTriggeredAlerts(
                  item,
                  isStale ? null : price
                );
                const returnPercent = positionReturn(item, price);
                const hasPosition =
                  finiteNumber(item.quantity) !== null &&
                  (item.quantity ?? 0) > 0 &&
                  finiteNumber(item.averageCost) !== null;
                const { currency } = inferInstrumentIdentity(item.symbol);
                const changeClass =
                  change === null || change === 0
                    ? "text-muted-foreground"
                    : change > 0
                      ? "text-up"
                      : "text-down";
                const returnClass =
                  returnPercent === null || returnPercent === 0
                    ? "text-muted-foreground"
                    : returnPercent > 0
                      ? "text-up"
                      : "text-down";

                return (
                  <Link
                    key={item.symbol}
                    href={`/stocks/${item.symbol}`}
                    className="flex shrink-0 items-center gap-1.5 whitespace-nowrap text-xs transition-opacity hover:opacity-75"
                  >
                    <span className="font-mono font-semibold text-foreground">
                      {item.symbol}
                    </span>
                    <span className="font-mono tabular-nums text-foreground">
                      {formatPrice(price, currencyPrefix(currency))}
                    </span>
                    <span className={cn("font-mono tabular-nums", changeClass)}>
                      {formatChange(change)}
                    </span>
                    {isStale ? (
                      <Badge
                        variant="outline"
                        className="h-4 border-warn/40 bg-warn/10 px-1.5 text-[10px] text-warn"
                      >
                        {freshness.localDateLabel
                          ? `截至 ${freshness.localDateLabel}`
                          : "行情时间未知"}
                      </Badge>
                    ) : null}
                    {isStale && fetchedLabel ? (
                      <span className="text-[10px] text-muted-foreground">
                        抓取 {fetchedLabel}
                      </span>
                    ) : null}
                    {hasPosition ? (
                      <Badge
                        variant="outline"
                        className={cn("h-4 px-1.5 text-[10px]", returnClass)}
                      >
                        持仓 {returnPercent === null
                          ? "—"
                          : `${returnPercent > 0 ? "+" : ""}${returnPercent.toFixed(1)}%`}
                        {isStale ? " · 旧价" : ""}
                      </Badge>
                    ) : null}
                    {triggeredAlerts.above ? (
                      <Badge
                        variant="outline"
                        className="h-4 border-warn/40 bg-warn/10 px-1.5 text-[10px] text-warn"
                      >
                        上破提醒
                      </Badge>
                    ) : null}
                    {triggeredAlerts.below ? (
                      <Badge
                        variant="outline"
                        className="h-4 border-warn/40 bg-warn/10 px-1.5 text-[10px] text-warn"
                      >
                        下破提醒
                      </Badge>
                    ) : null}
                  </Link>
                );
              })}
            </div>
          ))}
        </div>
      )}

      <Link
        href="/screener"
        className="ml-3 flex shrink-0 items-center border-l border-border pl-3 text-[11px] text-muted-foreground transition-colors hover:text-foreground"
      >
        管理
      </Link>
    </Card>
  );
}
