/**
 * 自选与市场筛选工作台
 * 路由：/screener
 */
"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
} from "react";
import Link from "next/link";
import {
  ArrowsClockwiseIcon,
  GearIcon,
  PlusIcon,
  StarIcon,
} from "@phosphor-icons/react";

import { EmptyState } from "@/components/empty-state";
import { GroupManagerDialog } from "@/components/watchlist/group-manager-dialog";
import { PortfolioSummary } from "@/components/watchlist/portfolio-summary";
import { WatchlistEditorDialog } from "@/components/watchlist/watchlist-editor-dialog";
import { WatchlistTable } from "@/components/watchlist/watchlist-table";
import type { WorkbenchQuote } from "@/components/watchlist/types";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  WATCHLIST_CHANGE_EVENT,
  WATCHLIST_KEY,
  WatchlistStorageError,
  addWatchlistGroup,
  getWatchlistClientId,
  getWatchlistSymbols,
  migrateLegacyWatchlistStateAtomically,
  mutateWatchlistState,
  parseWatchlistState,
  removeWatchlistGroup,
  removeWatchlistItem,
  renameWatchlistGroup,
  upsertWatchlistItem,
  validateWatchlistSymbol,
  type WatchlistItem,
  type WatchlistState,
} from "@/lib/watchlist";

interface ScreenerItem {
  symbol: string;
  name: string | null;
  price: number | null;
  change: number | null;
  change_percent: number | null;
  volume: number | null;
  exchange: string | null;
}

type ScreenerType =
  | "gainers"
  | "losers"
  | "active"
  | "undervalued_large_caps"
  | "undervalued_growth";

const SCREENER_TYPES: { key: ScreenerType; label: string; desc: string }[] = [
  { key: "gainers", label: "涨幅榜", desc: "当日涨幅最大" },
  { key: "losers", label: "跌幅榜", desc: "当日跌幅最大" },
  { key: "active", label: "活跃榜", desc: "成交量最大" },
  { key: "undervalued_large_caps", label: "低估值大盘", desc: "PE 低的蓝筹" },
  { key: "undervalued_growth", label: "低估值成长", desc: "PE 低的成长股" },
];

const EMPTY_WATCHLIST: WatchlistState = parseWatchlistState(null);
const STORAGE_FAILURE_NOTICE = "本地存储失败，未保存";

function fmtPrice(value: number | null | undefined): string {
  if (value == null) return "—";
  return value.toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function fmtPct(fraction: number | null | undefined): string {
  if (fraction == null) return "—";
  const sign = fraction > 0 ? "+" : "";
  return `${sign}${(fraction * 100).toFixed(2)}%`;
}

function fmtVolume(value: number | null | undefined): string {
  if (value == null) return "—";
  if (value >= 1e9) return `${(value / 1e9).toFixed(2)}B`;
  if (value >= 1e6) return `${(value / 1e6).toFixed(2)}M`;
  if (value >= 1e3) return `${(value / 1e3).toFixed(2)}K`;
  return value.toLocaleString("en-US");
}

function nullableNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function normalizeWorkbenchQuote(
  value: Record<string, unknown>
): WorkbenchQuote | null {
  if (typeof value.symbol !== "string" || !value.symbol.trim()) return null;

  return {
    symbol: value.symbol.trim().toUpperCase(),
    name: typeof value.name === "string" ? value.name : null,
    price: nullableNumber(value.last_price),
    changePercent: nullableNumber(value.change_percent),
    volume: nullableNumber(value.volume),
    dataAsOf: typeof value.data_as_of === "string" ? value.data_as_of : null,
    fetchedAt: typeof value.fetched_at === "string" ? value.fetched_at : null,
  };
}

function formatClockTime(value: Date): string {
  return value.toLocaleTimeString("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

function formatDataTime(value: Date, now: Date): string {
  if (
    value.getFullYear() === now.getFullYear() &&
    value.getMonth() === now.getMonth() &&
    value.getDate() === now.getDate()
  ) {
    return formatClockTime(value);
  }

  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${month}-${day} ${formatClockTime(value)}`;
}

export default function ScreenerPage() {
  const [watchlist, setWatchlist] = useState<WatchlistState>(EMPTY_WATCHLIST);
  const watchlistRef = useRef<WatchlistState>(EMPTY_WATCHLIST);
  const [mounted, setMounted] = useState(false);
  const [activeGroupId, setActiveGroupId] = useState<string | null>(null);
  const [newSymbol, setNewSymbol] = useState("");
  const [quotes, setQuotes] = useState<WorkbenchQuote[]>([]);
  const [freshnessNow, setFreshnessNow] = useState(() => new Date(0));
  const [pageRefreshedAt, setPageRefreshedAt] = useState<Date | null>(null);
  const [quoteLoading, setQuoteLoading] = useState(false);
  const [quoteError, setQuoteError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [addError, setAddError] = useState<string | null>(null);
  const [editingItem, setEditingItem] = useState<WatchlistItem | null>(null);
  const editingItemRef = useRef<WatchlistItem | null>(null);
  const [pageNotice, setPageNotice] = useState<string | null>(null);
  const [removeCandidate, setRemoveCandidate] =
    useState<WatchlistItem | null>(null);
  const [groupManagerOpen, setGroupManagerOpen] = useState(false);
  const [screenerType, setScreenerType] = useState<ScreenerType>("gainers");
  const [screenerData, setScreenerData] = useState<ScreenerItem[]>([]);
  const [screenerLoading, setScreenerLoading] = useState(true);
  const [screenerError, setScreenerError] = useState<string | null>(null);
  const quoteRequestIdRef = useRef(0);
  const quoteAbortControllerRef = useRef<AbortController | null>(null);

  const symbols = useMemo(() => getWatchlistSymbols(watchlist), [watchlist]);
  const symbolKey = symbols.join(",");
  const symbolKeyRef = useRef(symbolKey);
  const watchedSymbols = useMemo(() => new Set(symbols), [symbols]);
  const selectedGroupId =
    activeGroupId &&
    watchlist.groups.some((group) => group.id === activeGroupId)
      ? activeGroupId
      : null;
  const selectedGroupIdRef = useRef(selectedGroupId);
  const itemCounts = useMemo(
    () =>
      watchlist.items.reduce<Record<string, number>>((counts, item) => {
        counts[item.groupId] = (counts[item.groupId] ?? 0) + 1;
        return counts;
      }, {}),
    [watchlist.items]
  );
  const quoteDataWindow = useMemo(() => {
    const timestamps = quotes
      .map((quote) => (quote.dataAsOf ? Date.parse(quote.dataAsOf) : NaN))
      .filter(Number.isFinite);
    if (timestamps.length === 0) return null;
    return {
      oldest: new Date(Math.min(...timestamps)),
      latest: new Date(Math.max(...timestamps)),
    };
  }, [quotes]);
  const quoteFetchWindow = useMemo(() => {
    const timestamps = quotes
      .map((quote) => (quote.fetchedAt ? Date.parse(quote.fetchedAt) : NaN))
      .filter(Number.isFinite);
    if (timestamps.length === 0) return null;
    return {
      oldest: new Date(Math.min(...timestamps)),
      latest: new Date(Math.max(...timestamps)),
    };
  }, [quotes]);

  const closeEditor = useCallback(() => {
    editingItemRef.current = null;
    setEditingItem(null);
  }, []);

  const openEditor = useCallback((item: WatchlistItem) => {
    editingItemRef.current = item;
    setEditingItem(item);
    setPageNotice(null);
  }, []);

  const syncWatchlist = useCallback((next: WatchlistState) => {
    if (next.revision < watchlistRef.current.revision) return;

    const openedItem = editingItemRef.current;
    const isExternalWriter =
      Boolean(next.clientId) && next.clientId !== getWatchlistClientId();
    if (openedItem && isExternalWriter) {
      const currentItem = next.items.find(
        (item) => item.symbol === openedItem.symbol
      );
      if (!currentItem || currentItem.updatedAt !== openedItem.updatedAt) {
        editingItemRef.current = null;
        setEditingItem(null);
        setPageNotice("其他标签已更新，请重新打开编辑");
      }
    }

    watchlistRef.current = next;
    setWatchlist(next);
  }, []);

  useEffect(() => {
    symbolKeyRef.current = symbolKey;
    selectedGroupIdRef.current = selectedGroupId;
  }, [selectedGroupId, symbolKey]);

  useEffect(() => {
    const initialTick = window.requestAnimationFrame(() =>
      setFreshnessNow(new Date())
    );
    const timer = window.setInterval(() => setFreshnessNow(new Date()), 60_000);
    return () => {
      window.cancelAnimationFrame(initialTick);
      window.clearInterval(timer);
    };
  }, []);

  const persistWatchlist = useCallback(
    async (mutate: (current: WatchlistState) => WatchlistState) => {
      try {
        const saved = await mutateWatchlistState(mutate);
        syncWatchlist(saved);
        return saved;
      } catch (error: unknown) {
        if (error instanceof WatchlistStorageError) {
          setPageNotice(STORAGE_FAILURE_NOTICE);
        }
        throw error;
      }
    },
    [syncWatchlist]
  );

  const refreshQuotes = useCallback(async (requestedSymbols: string[]) => {
    const requestedKey = requestedSymbols.join(",");
    if (requestedKey !== symbolKeyRef.current) return;

    const requestId = quoteRequestIdRef.current + 1;
    quoteRequestIdRef.current = requestId;
    quoteAbortControllerRef.current?.abort();

    if (requestedSymbols.length === 0) {
      quoteAbortControllerRef.current = null;
      setQuotes([]);
      setQuoteError(null);
      setPageRefreshedAt(null);
      setQuoteLoading(false);
      return;
    }

    const controller = new AbortController();
    quoteAbortControllerRef.current = controller;
    setQuoteLoading(true);
    setQuoteError(null);

    try {
      const response = await fetch(
        `/api/quotes?symbols=${encodeURIComponent(requestedKey)}&_t=${Date.now()}`,
        { cache: "no-store", signal: controller.signal }
      );
      if (!response.ok) throw new Error("quote request failed");
      const payload: unknown = await response.json();
      const normalized = (Array.isArray(payload) ? payload : [])
        .filter(isRecord)
        .map(normalizeWorkbenchQuote)
        .filter((item): item is WorkbenchQuote => item !== null);

      if (
        controller.signal.aborted ||
        requestId !== quoteRequestIdRef.current ||
        requestedKey !== symbolKeyRef.current
      ) {
        return;
      }

      setQuotes(normalized);
      setPageRefreshedAt(new Date());
      if (normalized.length === 0) {
        setQuoteError("报价暂不可用，已保留自选与交易计划");
      }
    } catch (error: unknown) {
      if (
        controller.signal.aborted ||
        (error instanceof DOMException && error.name === "AbortError")
      ) {
        return;
      }
      if (
        requestId === quoteRequestIdRef.current &&
        requestedKey === symbolKeyRef.current
      ) {
        setQuoteError("报价刷新失败，请稍后重试");
      }
    } finally {
      if (
        requestId === quoteRequestIdRef.current &&
        requestedKey === symbolKeyRef.current
      ) {
        setQuoteLoading(false);
        if (quoteAbortControllerRef.current === controller) {
          quoteAbortControllerRef.current = null;
        }
      }
    }
  }, []);

  useEffect(() => {
    let raw: string | null = null;
    let storageUnavailable = false;
    try {
      raw = window.localStorage.getItem(WATCHLIST_KEY);
    } catch {
      storageUnavailable = true;
    }
    const parsed = parseWatchlistState(raw);
    const isLegacy = (() => {
      if (!raw) return false;
      try {
        const value: unknown = JSON.parse(raw);
        return Array.isArray(value);
      } catch {
        return false;
      }
    })();

    watchlistRef.current = parsed;
    const initialize = window.setTimeout(() => {
      if (storageUnavailable) setPageNotice(STORAGE_FAILURE_NOTICE);
      syncWatchlist(watchlistRef.current);
      setMounted(true);
    }, 0);
    if (isLegacy) {
      void (async () => {
        try {
          const migrated = await migrateLegacyWatchlistStateAtomically(parsed);
          syncWatchlist(migrated);
        } catch (error: unknown) {
          if (error instanceof WatchlistStorageError) {
            setPageNotice(STORAGE_FAILURE_NOTICE);
          }
        }
      })();
    }

    const syncFromStorage = (rawValue: string | null) => {
      syncWatchlist(parseWatchlistState(rawValue));
    };
    const handleWatchlistChange = (event: Event) => {
      const detail = (event as CustomEvent<WatchlistState | undefined>).detail;
      syncWatchlist(
        detail ?? parseWatchlistState(window.localStorage.getItem(WATCHLIST_KEY))
      );
    };
    const handleStorage = (event: StorageEvent) => {
      if (event.key === WATCHLIST_KEY) syncFromStorage(event.newValue);
    };

    window.addEventListener(WATCHLIST_CHANGE_EVENT, handleWatchlistChange);
    window.addEventListener("storage", handleStorage);
    return () => {
      window.clearTimeout(initialize);
      window.removeEventListener(WATCHLIST_CHANGE_EVENT, handleWatchlistChange);
      window.removeEventListener("storage", handleStorage);
    };
  }, [syncWatchlist]);

  useEffect(() => {
    if (!mounted) return;
    const requestedSymbols = symbolKey ? symbolKey.split(",") : [];
    const initialRefresh = window.setTimeout(
      () => void refreshQuotes(requestedSymbols),
      0
    );
    const timer = window.setInterval(
      () => void refreshQuotes(requestedSymbols),
      30_000
    );
    return () => {
      window.clearTimeout(initialRefresh);
      window.clearInterval(timer);
      quoteRequestIdRef.current += 1;
      quoteAbortControllerRef.current?.abort();
      quoteAbortControllerRef.current = null;
    };
  }, [mounted, refreshQuotes, symbolKey]);

  useEffect(() => {
    const controller = new AbortController();
    const request = window.setTimeout(() => {
      fetch(`/api/screener?type=${screenerType}`, {
        cache: "no-store",
        signal: controller.signal,
      })
        .then((response) => {
          if (!response.ok) throw new Error("screener request failed");
          return response.json() as Promise<unknown>;
        })
        .then((data) => {
          setScreenerData(Array.isArray(data) ? (data as ScreenerItem[]) : []);
        })
        .catch((error: unknown) => {
          if (error instanceof DOMException && error.name === "AbortError") return;
          setScreenerData([]);
          setScreenerError("市场筛选暂不可用，请稍后重试");
        })
        .finally(() => {
          if (!controller.signal.aborted) setScreenerLoading(false);
        });
    }, 0);

    return () => {
      window.clearTimeout(request);
      controller.abort();
    };
  }, [screenerType]);

  async function addToWatchlist(input: string) {
    const requested = input.trim();
    if (!requested) {
      setAddError("请输入股票代码");
      return;
    }

    setAddError(null);
    setAdding(true);
    try {
      const result = await validateWatchlistSymbol(requested);
      if (!result.valid) {
        setAddError("未找到该股票，请输入合法的股票代码");
        return;
      }

      const requestedGroupId = selectedGroupIdRef.current;
      let existingItem: WatchlistItem | null = null;
      let resolvedGroupId = "watch";
      await persistWatchlist((current) => {
        const existing = current.items.find(
          (item) => item.symbol === result.symbol
        );
        if (existing) {
          existingItem = existing;
          return current;
        }

        resolvedGroupId =
          requestedGroupId &&
          current.groups.some((group) => group.id === requestedGroupId)
            ? requestedGroupId
            : "watch";
        return upsertWatchlistItem(current, {
          symbol: result.symbol,
          groupId: resolvedGroupId,
        });
      });
      if (existingItem) {
        openEditor(existingItem);
      } else if (requestedGroupId) {
        setActiveGroupId(resolvedGroupId);
      }
      setNewSymbol("");
    } catch (error: unknown) {
      setAddError(
        error instanceof WatchlistStorageError
          ? STORAGE_FAILURE_NOTICE
          : "暂时无法校验股票代码，请稍后重试"
      );
    } finally {
      setAdding(false);
    }
  }

  function handleAddSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void addToWatchlist(newSymbol);
  }

  async function handleEditorSave(
    item: WatchlistItem,
    expectedUpdatedAt: string
  ): Promise<boolean | string> {
    let conflict = false;
    try {
      await persistWatchlist((current) => {
        const currentItem = current.items.find(
          (candidate) => candidate.symbol === item.symbol
        );
        if (!currentItem || currentItem.updatedAt !== expectedUpdatedAt) {
          conflict = true;
          return current;
        }
        return upsertWatchlistItem(current, item);
      });
    } catch (error: unknown) {
      if (error instanceof WatchlistStorageError) {
        setPageNotice(STORAGE_FAILURE_NOTICE);
      }
      throw error;
    }

    if (conflict) {
      const message = "其他标签已更新，请重新打开编辑";
      setPageNotice(message);
      return message;
    }
    return true;
  }

  async function confirmRemove() {
    if (!removeCandidate) return;
    const removedSymbol = removeCandidate.symbol;
    try {
      await persistWatchlist((current) =>
        removeWatchlistItem(current, removedSymbol)
      );
      setQuotes((current) =>
        current.filter((quote) => quote.symbol !== removedSymbol)
      );
      setRemoveCandidate(null);
    } catch (error: unknown) {
      if (error instanceof WatchlistStorageError) {
        setPageNotice(STORAGE_FAILURE_NOTICE);
      }
    }
  }

  function toggleScreenerWatchlist(item: ScreenerItem) {
    const existing = watchlistRef.current.items.find(
      (watchlistItem) => watchlistItem.symbol === item.symbol
    );
    if (existing) {
      setRemoveCandidate(existing);
      return;
    }
    void addToWatchlist(item.symbol);
  }

  return (
    <main className="min-w-0 space-y-6 px-4 pb-8 lg:px-6">
      <section className="min-w-0 space-y-4" aria-labelledby="watchlist-title">
        <header className="flex flex-col gap-3 border-b border-border pb-4 xl:flex-row xl:items-end xl:justify-between">
          <div className="min-w-0">
            <h1
              id="watchlist-title"
              className="font-heading text-xl font-semibold text-foreground sm:text-2xl"
            >
              自选与交易计划
            </h1>
            <p className="mt-1 text-sm text-muted-foreground">
              本地保存 · 按原生币种核算
            </p>
          </div>

          <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-center">
            <form
              className="flex min-w-0 flex-1 gap-2 sm:w-[22rem]"
              onSubmit={handleAddSubmit}
            >
              <Input
                value={newSymbol}
                placeholder="代码，如 AAPL、00700.HK"
                aria-label="添加股票代码"
                aria-invalid={Boolean(addError)}
                aria-describedby={addError ? "watchlist-add-error" : undefined}
                className="min-w-0 flex-1 font-mono"
                onChange={(event) => {
                  setNewSymbol(event.target.value);
                  setAddError(null);
                }}
              />
              <Tooltip>
                <TooltipTrigger
                  render={
                    <Button
                      type="submit"
                      size="icon"
                      disabled={adding}
                      aria-label="添加自选"
                    />
                  }
                >
                  <PlusIcon />
                </TooltipTrigger>
                <TooltipContent>添加到当前分组</TooltipContent>
              </Tooltip>
            </form>
            <div className="flex gap-2">
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => setGroupManagerOpen(true)}
              >
                <GearIcon data-icon="inline-start" />
                分组
              </Button>
              <Tooltip>
                <TooltipTrigger
                  render={
                    <Button
                      type="button"
                      variant="outline"
                      size="icon-sm"
                      disabled={quoteLoading}
                      aria-label="刷新自选报价"
                      onClick={() => void refreshQuotes(symbols)}
                    />
                  }
                >
                  <ArrowsClockwiseIcon />
                </TooltipTrigger>
                <TooltipContent>刷新报价</TooltipContent>
              </Tooltip>
            </div>
          </div>
        </header>

        {addError ? (
          <p id="watchlist-add-error" role="alert" className="text-sm text-destructive">
            {addError}
          </p>
        ) : null}

        {pageNotice ? (
          <p
            role="status"
            className="border-l-2 border-warn pl-3 text-sm text-warn"
          >
            {pageNotice}
          </p>
        ) : null}

        <PortfolioSummary
          items={watchlist.items}
          quotes={quotes}
          now={freshnessNow}
        />

        <Card size="sm" className="min-w-0">
          <CardHeader className="border-b">
            <div className="flex min-w-0 flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
              <div>
                <CardTitle>自选清单</CardTitle>
                <CardDescription className="mt-1 flex flex-wrap gap-x-2 gap-y-1">
                  <span>{watchlist.items.length} 个标的</span>
                  <span>
                    {quoteDataWindow
                      ? `行情数据截至 ${formatDataTime(quoteDataWindow.oldest, freshnessNow)}`
                      : "行情时间未知"}
                  </span>
                  {quoteDataWindow &&
                  quoteDataWindow.latest.getTime() !==
                    quoteDataWindow.oldest.getTime() ? (
                    <span>
                      最新行情 {formatDataTime(quoteDataWindow.latest, freshnessNow)}
                    </span>
                  ) : null}
                  <span>
                    {quoteFetchWindow
                      ? `抓取于 ${formatDataTime(quoteFetchWindow.oldest, freshnessNow)}`
                      : "抓取时间未知"}
                  </span>
                  {quoteFetchWindow &&
                  quoteFetchWindow.latest.getTime() !==
                    quoteFetchWindow.oldest.getTime() ? (
                    <span>
                      最晚抓取 {formatDataTime(quoteFetchWindow.latest, freshnessNow)}
                    </span>
                  ) : null}
                  <span>
                    {pageRefreshedAt
                      ? `页面刷新于 ${formatClockTime(pageRefreshedAt)}`
                      : "页面尚未刷新"}
                  </span>
                </CardDescription>
              </div>
              <Tabs
                value={selectedGroupId ?? "all"}
                onValueChange={(value) =>
                  setActiveGroupId(value === "all" ? null : value)
                }
                className="min-w-0"
              >
                <TabsList className="max-w-full justify-start overflow-x-auto">
                  <TabsTrigger value="all">
                    全部 {watchlist.items.length}
                  </TabsTrigger>
                  {[...watchlist.groups]
                    .sort((left, right) => left.order - right.order)
                    .map((group) => (
                      <TabsTrigger key={group.id} value={group.id}>
                        {group.name}{" "}
                        {
                          watchlist.items.filter(
                            (item) => item.groupId === group.id
                          ).length
                        }
                      </TabsTrigger>
                    ))}
                </TabsList>
              </Tabs>
            </div>
            {quoteError ? (
              <p role="alert" className="mt-2 text-xs text-warn">
                {quoteError}
              </p>
            ) : null}
          </CardHeader>
          <CardContent className="min-w-0 px-0">
            <WatchlistTable
              items={watchlist.items}
              groups={watchlist.groups}
              quotes={quotes}
              now={freshnessNow}
              activeGroupId={selectedGroupId}
              onEdit={openEditor}
              onRemove={setRemoveCandidate}
            />
          </CardContent>
        </Card>
      </section>

      <section aria-labelledby="market-screener-title">
        <Card size="sm" className="min-w-0">
          <CardHeader className="border-b">
            <CardTitle id="market-screener-title">市场筛选</CardTitle>
            <CardDescription>
              {SCREENER_TYPES.find((item) => item.key === screenerType)?.desc}
            </CardDescription>
          </CardHeader>
          <CardContent className="min-w-0 space-y-4 px-0">
            <Tabs
              value={screenerType}
              onValueChange={(value) => {
                setScreenerLoading(true);
                setScreenerError(null);
                setScreenerType(value as ScreenerType);
              }}
              className="min-w-0 px-3"
            >
              <TabsList className="max-w-full justify-start overflow-x-auto">
                {SCREENER_TYPES.map((item) => (
                  <TabsTrigger key={item.key} value={item.key}>
                    {item.label}
                  </TabsTrigger>
                ))}
              </TabsList>
            </Tabs>

            {screenerError ? (
              <p role="alert" className="px-3 text-sm text-warn">
                {screenerError}
              </p>
            ) : null}

            {screenerLoading ? (
              <div className="space-y-2 px-3 pb-1">
                {Array.from({ length: 8 }).map((_, index) => (
                  <Skeleton key={index} className="h-8 w-full" />
                ))}
              </div>
            ) : screenerData.length > 0 ? (
              <Table className="min-w-[760px]">
                <TableHeader>
                  <TableRow>
                    <TableHead className="pl-4">代码</TableHead>
                    <TableHead>名称</TableHead>
                    <TableHead className="text-right">价格</TableHead>
                    <TableHead className="text-right">涨跌</TableHead>
                    <TableHead className="text-right">成交量</TableHead>
                    <TableHead className="w-16 pr-4 text-right">自选</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {screenerData.slice(0, 20).map((item) => {
                    const isUp = (item.change_percent ?? 0) >= 0;
                    const isWatched = watchedSymbols.has(item.symbol);
                    return (
                      <TableRow key={item.symbol}>
                        <TableCell className="pl-4">
                          <Link
                            href={`/stocks/${item.symbol}`}
                            className="font-mono font-semibold hover:text-accent"
                          >
                            {item.symbol}
                          </Link>
                        </TableCell>
                        <TableCell className="max-w-48 truncate text-xs text-muted-foreground">
                          {item.name ?? "—"}
                        </TableCell>
                        <TableCell className="text-right font-mono tabular-nums">
                          {fmtPrice(item.price)}
                        </TableCell>
                        <TableCell
                          className={`text-right font-mono tabular-nums ${
                            isUp ? "text-up" : "text-down"
                          }`}
                        >
                          {fmtPct(item.change_percent)}
                        </TableCell>
                        <TableCell className="text-right font-mono text-muted-foreground tabular-nums">
                          {fmtVolume(item.volume)}
                        </TableCell>
                        <TableCell className="pr-4 text-right">
                          <Tooltip>
                            <TooltipTrigger
                              render={
                                <Button
                                  type="button"
                                  variant="ghost"
                                  size="icon-sm"
                                  aria-label={
                                    isWatched
                                      ? `从自选移除 ${item.symbol}`
                                      : `添加自选 ${item.symbol}`
                                  }
                                  className={
                                    isWatched
                                      ? "text-accent"
                                      : "text-muted-foreground hover:text-accent"
                                  }
                                  onClick={() => toggleScreenerWatchlist(item)}
                                />
                              }
                            >
                              <StarIcon weight={isWatched ? "fill" : "regular"} />
                            </TooltipTrigger>
                            <TooltipContent>
                              {isWatched ? "移出自选" : "加入自选"}
                            </TooltipContent>
                          </Tooltip>
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            ) : (
              <EmptyState title="无筛选结果" description="该榜单当前没有可用数据。" />
            )}
          </CardContent>
        </Card>
      </section>

      <WatchlistEditorDialog
        open={Boolean(editingItem)}
        onOpenChange={(open) => {
          if (!open) closeEditor();
        }}
        item={editingItem}
        groups={watchlist.groups}
        onSave={handleEditorSave}
      />

      <GroupManagerDialog
        open={groupManagerOpen}
        onOpenChange={setGroupManagerOpen}
        groups={watchlist.groups}
        itemCounts={itemCounts}
        onAdd={async (name) => {
          try {
            await persistWatchlist((current) =>
              addWatchlistGroup(current, name)
            );
          } catch (error: unknown) {
            if (error instanceof WatchlistStorageError) {
              setPageNotice(STORAGE_FAILURE_NOTICE);
            }
            throw error;
          }
        }}
        onRename={async (id, name) => {
          try {
            await persistWatchlist((current) =>
              renameWatchlistGroup(current, id, name)
            );
          } catch (error: unknown) {
            if (error instanceof WatchlistStorageError) {
              setPageNotice(STORAGE_FAILURE_NOTICE);
            }
            throw error;
          }
        }}
        onRemove={async (id) => {
          try {
            await persistWatchlist((current) =>
              removeWatchlistGroup(current, id)
            );
          } catch (error: unknown) {
            if (error instanceof WatchlistStorageError) {
              setPageNotice(STORAGE_FAILURE_NOTICE);
            }
            throw error;
          }
        }}
      />

      <Dialog
        open={Boolean(removeCandidate)}
        onOpenChange={(open) => {
          if (!open) setRemoveCandidate(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>移出自选</DialogTitle>
            <DialogDescription>
              将 {removeCandidate?.symbol} 移出后，其仓位、提醒和交易逻辑会一并删除。
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setRemoveCandidate(null)}
            >
              取消
            </Button>
            <Button
              type="button"
              variant="destructive"
              onClick={() => void confirmRemove()}
            >
              确认移出
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </main>
  );
}
