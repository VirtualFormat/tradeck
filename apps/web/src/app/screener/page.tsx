/**
 * 自选股 + 筛选器页
 * 路由：/screener
 * - 自选股：localStorage 存储，添加/删除
 * - 筛选器：gainers/losers/active/undervalued_large_caps/undervalued_growth
 */
"use client";

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
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
import { PlusIcon, TrashIcon, StarIcon } from "@phosphor-icons/react";
import { EmptyState } from "@/components/empty-state";
import {
  fetchValidQuotes,
  parseWatchlist,
  reconcileWatchlist,
  validateWatchlistSymbols,
  validateWatchlistSymbol,
  WATCHLIST_KEY,
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

function fmtPrice(v: number | null | undefined): string {
  if (v == null) return "—";
  return v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function fmtPct(fraction: number | null | undefined): string {
  if (fraction == null) return "—";
  const sign = fraction > 0 ? "+" : "";
  return `${sign}${(fraction * 100).toFixed(2)}%`;
}

function fmtVolume(v: number | null | undefined): string {
  if (v == null) return "—";
  if (v >= 1e9) return `${(v / 1e9).toFixed(2)}B`;
  if (v >= 1e6) return `${(v / 1e6).toFixed(2)}M`;
  if (v >= 1e3) return `${(v / 1e3).toFixed(2)}K`;
  return v.toLocaleString("en-US");
}

export default function ScreenerPage() {
  const [watchlist, setWatchlist] = useState<string[]>([]);
  const [newSymbol, setNewSymbol] = useState("");
  const [screenerType, setScreenerType] = useState<ScreenerType>("gainers");
  const [screenerData, setScreenerData] = useState<ScreenerItem[]>([]);
  const [watchlistData, setWatchlistData] = useState<ScreenerItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [adding, setAdding] = useState(false);
  const [addError, setAddError] = useState<string | null>(null);

  // 加载自选股
  useEffect(() => {
    const saved = localStorage.getItem(WATCHLIST_KEY);
    if (!saved) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setWatchlist(parseWatchlist(saved));
  }, []);

  // 保存自选股
  const saveWatchlist = useCallback((list: string[]) => {
    localStorage.setItem(WATCHLIST_KEY, JSON.stringify(list));
    setWatchlist(list);
    setWatchlistData((current) =>
      current.filter((item) => list.includes(item.symbol))
    );
  }, []);

  async function addToWatchlist(symbol: string) {
    setAddError(null);
    setAdding(true);
    try {
      const result = await validateWatchlistSymbol(symbol);
      if (!result.valid) {
        setAddError("未找到该股票，请输入合法的股票代码");
        return;
      }
      if (!watchlist.includes(result.symbol)) {
        saveWatchlist([...watchlist, result.symbol]);
      }
      setNewSymbol("");
    } catch {
      setAddError("暂时无法校验股票代码，请稍后重试");
    } finally {
      setAdding(false);
    }
  }

  function removeFromWatchlist(symbol: string) {
    saveWatchlist(watchlist.filter((s) => s !== symbol));
  }

  // 拉筛选数据
  useEffect(() => {
    fetch(`/api/screener?type=${screenerType}`)
      .then((r) => r.json())
      .then((data: ScreenerItem[]) => {
        setScreenerData(data);
        setLoading(false);
      })
      .catch(() => {
        setScreenerData([]);
        setLoading(false);
      });
  }, [screenerType]);

  // 拉自选股报价
  useEffect(() => {
    if (watchlist.length === 0) return;
    let cancelled = false;
    // 加时间戳避免浏览器缓存
    validateWatchlistSymbols(watchlist)
      .then(async (validSymbols) => {
        if (cancelled) return;
        const cleaned = reconcileWatchlist(watchlist, validSymbols);
        if (cleaned.length !== watchlist.length) {
          saveWatchlist(cleaned);
        }
        const data = await fetchValidQuotes<ScreenerItem>(cleaned);
        if (cancelled) return;
        setWatchlistData(data);
      })
      .catch(() => setWatchlistData([]));
    return () => {
      cancelled = true;
    };
  }, [saveWatchlist, watchlist]);

  return (
    <div className="px-4 lg:px-6">
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
          {/* 自选股（占 1 列） */}
          <Card className="lg:col-span-1">
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-sm">
                <StarIcon className="h-4 w-4" />
                自选股 ({watchlist.length})
              </CardTitle>
            </CardHeader>
            <CardContent>
              {/* 添加 */}
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  addToWatchlist(newSymbol);
                }}
                className="mb-3 flex gap-2"
              >
                <Input
                  value={newSymbol}
                  onChange={(e) => {
                    setNewSymbol(e.target.value);
                    if (addError) setAddError(null);
                  }}
                  placeholder="代码（如 AAPL）"
                  aria-invalid={Boolean(addError)}
                  aria-describedby={addError ? "watchlist-add-error" : undefined}
                  className="flex-1"
                />
                <Button type="submit" size="sm" disabled={adding}>
                  <PlusIcon className="h-3 w-3" />
                </Button>
              </form>
              {addError ? (
                <p
                  id="watchlist-add-error"
                  role="alert"
                  className="-mt-1 mb-3 text-xs text-destructive"
                >
                  {addError}
                </p>
              ) : null}

              {watchlistData.length > 0 ? (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>代码</TableHead>
                      <TableHead className="text-right">价格</TableHead>
                      <TableHead className="text-right">涨跌</TableHead>
                      <TableHead></TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {watchlistData.map((item) => {
                      const up = (item.change_percent ?? 0) >= 0;
                      return (
                        <TableRow key={item.symbol}>
                          <TableCell>
                            <Link
                              href={`/stocks/${item.symbol}`}
                              className="font-medium hover:text-accent"
                            >
                              {item.symbol}
                            </Link>
                          </TableCell>
                          <TableCell className="text-right tab-nums">
                            {fmtPrice(item.price)}
                          </TableCell>
                          <TableCell
                            className={`text-right tab-nums ${
                              up ? "text-up" : "text-down"
                            }`}
                          >
                            {fmtPct(item.change_percent)}
                          </TableCell>
                          <TableCell>
                            <Button
                              variant="ghost"
                              size="icon-xs"
                              onClick={() => removeFromWatchlist(item.symbol)}
                              className="text-muted-foreground hover:text-up"
                            >
                              <TrashIcon />
                            </Button>
                          </TableCell>
                        </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
              ) : (
                <EmptyState
                  title="暂无自选股"
                  description="输入代码添加"
                />
              )}
            </CardContent>
          </Card>

          {/* 筛选器（占 2 列） */}
          <Card className="lg:col-span-2">
            <CardHeader>
              <CardTitle className="text-sm">市场筛选</CardTitle>
            </CardHeader>
            <CardContent>
              {/* 类型切换 */}
              <Tabs
                value={screenerType}
                onValueChange={(v) => {
                  setLoading(true);
                  setScreenerType(v as ScreenerType);
                }}
                className="mb-4 flex-row gap-0"
              >
                <TabsList className="rounded-md border border-border bg-panel-2 p-0.5">
                  {SCREENER_TYPES.map((t) => (
                    <TabsTrigger
                      key={t.key}
                      value={t.key}
                      className="rounded-sm px-2.5 py-1 text-[11px] font-medium text-muted-foreground hover:text-foreground data-active:bg-accent data-active:text-accent-foreground"
                    >
                      {t.label}
                    </TabsTrigger>
                  ))}
                </TabsList>
              </Tabs>

              <p className="mb-3 text-xs text-muted-foreground">
                {SCREENER_TYPES.find((t) => t.key === screenerType)?.desc}
              </p>

              {/* 筛选结果 */}
              {loading ? (
                <div className="space-y-2 py-1">
                  {Array.from({ length: 8 }).map((_, i) => (
                    <Skeleton key={i} className="h-6 w-full" />
                  ))}
                </div>
              ) : screenerData.length > 0 ? (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>代码</TableHead>
                      <TableHead>名称</TableHead>
                      <TableHead className="text-right">价格</TableHead>
                      <TableHead className="text-right">涨跌</TableHead>
                      <TableHead className="text-right">成交量</TableHead>
                      <TableHead></TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {screenerData.slice(0, 20).map((item) => {
                      const up = (item.change_percent ?? 0) >= 0;
                      const inWatchlist = watchlist.includes(item.symbol);
                      return (
                        <TableRow key={item.symbol}>
                          <TableCell>
                            <Link
                              href={`/stocks/${item.symbol}`}
                              className="font-medium hover:text-accent"
                            >
                              {item.symbol}
                            </Link>
                          </TableCell>
                          <TableCell className="text-xs text-fg-dim truncate max-w-32">
                            {item.name ?? "—"}
                          </TableCell>
                          <TableCell className="text-right tab-nums">
                            {fmtPrice(item.price)}
                          </TableCell>
                          <TableCell
                            className={`text-right tab-nums ${
                              up ? "text-up" : "text-down"
                            }`}
                          >
                            {fmtPct(item.change_percent)}
                          </TableCell>
                          <TableCell className="text-right tab-nums text-muted-foreground">
                            {fmtVolume(item.volume)}
                          </TableCell>
                          <TableCell>
                            <Button
                              variant="ghost"
                              size="icon-xs"
                              onClick={() =>
                                inWatchlist
                                  ? removeFromWatchlist(item.symbol)
                                  : addToWatchlist(item.symbol)
                              }
                              className={
                                inWatchlist
                                  ? "text-accent"
                                  : "text-muted-foreground hover:text-accent"
                              }
                            >
                              <StarIcon
                                weight={inWatchlist ? "fill" : "regular"}
                              />
                            </Button>
                          </TableCell>
                        </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
              ) : (
                <EmptyState title="无数据" />
              )}
            </CardContent>
          </Card>
        </div>
    </div>
  );
}
