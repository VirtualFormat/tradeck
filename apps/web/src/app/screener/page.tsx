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
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Plus, Trash2, Star } from "lucide-react";

const WATCHLIST_KEY = "tradeck-watchlist";

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
  const [loading, setLoading] = useState(false);

  // 加载自选股
  useEffect(() => {
    const saved = localStorage.getItem(WATCHLIST_KEY);
    if (saved) {
      try {
        setWatchlist(JSON.parse(saved));
      } catch {
        // ignore
      }
    }
  }, []);

  // 保存自选股
  const saveWatchlist = useCallback((list: string[]) => {
    localStorage.setItem(WATCHLIST_KEY, JSON.stringify(list));
    setWatchlist(list);
  }, []);

  function addToWatchlist(symbol: string) {
    const trimmed = symbol.trim().toUpperCase();
    if (!trimmed || watchlist.includes(trimmed)) return;
    saveWatchlist([...watchlist, trimmed]);
    setNewSymbol("");
  }

  function removeFromWatchlist(symbol: string) {
    saveWatchlist(watchlist.filter((s) => s !== symbol));
  }

  // 拉筛选数据
  useEffect(() => {
    setLoading(true);
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
    if (watchlist.length === 0) {
      setWatchlistData([]);
      return;
    }
    // 加时间戳避免浏览器缓存
    fetch(`/api/quotes?symbols=${watchlist.join(",")}&_t=${Date.now()}`)
      .then((r) => r.json())
      .then((data: ScreenerItem[]) => setWatchlistData(data))
      .catch(() => setWatchlistData([]));
  }, [watchlist]);

  return (
    <>
        <header className="mb-6 border-b border-border pb-3">
          <h1 className="text-lg font-semibold">自选股 + 筛选器</h1>
          <p className="text-[10px] uppercase tracking-[0.18em] text-muted">
            Watchlist + Screener · yfinance
          </p>
        </header>

        <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
          {/* 自选股（占 1 列） */}
          <Card className="lg:col-span-1">
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-sm">
                <Star className="h-4 w-4" />
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
                  onChange={(e) => setNewSymbol(e.target.value)}
                  placeholder="代码（如 AAPL）"
                  className="flex-1"
                />
                <Button type="submit" size="sm">
                  <Plus className="h-3 w-3" />
                </Button>
              </form>

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
                            <button
                              onClick={() => removeFromWatchlist(item.symbol)}
                              className="text-muted hover:text-up"
                            >
                              <Trash2 className="h-3 w-3" />
                            </button>
                          </TableCell>
                        </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
              ) : (
                <div className="py-8 text-center text-xs text-muted">
                  暂无自选股，输入代码添加
                </div>
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
              <div className="mb-4 flex flex-wrap gap-1.5">
                {SCREENER_TYPES.map((t) => (
                  <Badge
                    key={t.key}
                    variant={screenerType === t.key ? "default" : "secondary"}
                    className="cursor-pointer"
                    onClick={() => setScreenerType(t.key)}
                  >
                    {t.label}
                  </Badge>
                ))}
              </div>

              <p className="mb-3 text-xs text-muted">
                {SCREENER_TYPES.find((t) => t.key === screenerType)?.desc}
              </p>

              {/* 筛选结果 */}
              {loading ? (
                <div className="py-8 text-center text-xs text-muted">
                  加载中...
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
                          <TableCell className="text-right tab-nums text-muted">
                            {fmtVolume(item.volume)}
                          </TableCell>
                          <TableCell>
                            <button
                              onClick={() =>
                                inWatchlist
                                  ? removeFromWatchlist(item.symbol)
                                  : addToWatchlist(item.symbol)
                              }
                              className={
                                inWatchlist
                                  ? "text-accent"
                                  : "text-muted hover:text-accent"
                              }
                            >
                              <Star
                                className="h-3 w-3"
                                fill={inWatchlist ? "currentColor" : "none"}
                              />
                            </button>
                          </TableCell>
                        </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
              ) : (
                <div className="py-8 text-center text-xs text-muted">
                  无数据
                </div>
              )}
            </CardContent>
          </Card>
        </div>
    </>
  );
}
