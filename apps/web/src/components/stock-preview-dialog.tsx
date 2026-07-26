/**
 * 个股预览弹窗（参照 tickflow StockPreviewDialog）
 * - shadcn Dialog + TradingView K 线 + 报价信息条
 * - 点击任意股票行触发；弹窗内可跳转个股详情页
 */
"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { ArrowSquareOutIcon } from "@phosphor-icons/react";

import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { TradingViewChart, type KlinePoint } from "@/components/tradingview-chart";

interface QuoteInfo {
  symbol: string;
  name: string | null;
  last_price: number | null;
  change: number | null;
  change_percent: number | null;
  volume: number | null;
}

interface HistoricalRow {
  date: string;
  open: number | null;
  high: number | null;
  low: number | null;
  close: number | null;
}

function fmtVol(v: number | null | undefined): string {
  if (v == null) return "—";
  if (v >= 1e9) return `${(v / 1e9).toFixed(2)}B`;
  if (v >= 1e6) return `${(v / 1e6).toFixed(2)}M`;
  if (v >= 1e3) return `${(v / 1e3).toFixed(2)}K`;
  return String(v);
}

export function StockPreviewDialog({
  symbol,
  name,
  open,
  onOpenChange,
}: {
  symbol: string;
  name?: string | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const [quote, setQuote] = useState<QuoteInfo | null>(null);
  const [kline, setKline] = useState<KlinePoint[]>([]);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    fetch(`/api/quotes?symbols=${encodeURIComponent(symbol)}`)
      .then((r) => (r.ok ? r.json() : []))
      .then((arr: QuoteInfo[]) => {
        if (!cancelled && Array.isArray(arr) && arr.length > 0) {
          setQuote(arr[0]);
        }
      })
      .catch(() => {});
    fetch(`/api/historical?symbol=${encodeURIComponent(symbol)}&days=180`)
      .then((r) => (r.ok ? r.json() : []))
      .then((arr: HistoricalRow[]) => {
        if (cancelled || !Array.isArray(arr)) return;
        setKline(
          arr
            .filter(
              (d) =>
                d.open != null &&
                d.high != null &&
                d.low != null &&
                d.close != null
            )
            .map((d) => ({
              time: d.date,
              open: d.open as number,
              high: d.high as number,
              low: d.low as number,
              close: d.close as number,
            }))
        );
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [open, symbol]);

  const pct = quote?.change_percent;
  const up = (pct ?? 0) >= 0;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-4xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            {name ?? symbol}
            <Badge variant="secondary">{symbol}</Badge>
          </DialogTitle>
          <DialogDescription>TradingView K 线 · 日线</DialogDescription>
          <div className="flex items-center gap-3 pt-1">
            {quote && (
              <span className="tab-nums inline-flex items-center gap-2 text-xs">
                <span className="text-sm font-semibold text-fg">
                  {quote.last_price ?? "—"}
                </span>
                <span className={up ? "text-up" : "text-down"}>
                  {pct != null
                    ? `${up ? "+" : ""}${pct.toFixed(2)}%`
                    : "—"}
                </span>
                <span className="text-muted-foreground">
                  量 {fmtVol(quote.volume)}
                </span>
              </span>
            )}
            <Link
              href={`/stocks/${symbol}`}
              className="inline-flex items-center gap-1 text-xs text-accent hover:underline"
            >
              详情页
              <ArrowSquareOutIcon className="size-3" />
            </Link>
          </div>
        </DialogHeader>
        {open && <TradingViewChart data={kline} height={480} />}
      </DialogContent>
    </Dialog>
  );
}

/** 触发器：包裹股票行，点击打开预览弹窗（children 可为服务端渲染内容） */
export function StockPreviewTrigger({
  symbol,
  name,
  children,
}: {
  symbol: string;
  name?: string | null;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const handleOpen = useCallback(() => setOpen(true), []);
  return (
    <>
      <div
        role="button"
        tabIndex={0}
        onClick={handleOpen}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") handleOpen();
        }}
        className="cursor-pointer"
      >
        {children}
      </div>
      <StockPreviewDialog
        symbol={symbol}
        name={name}
        open={open}
        onOpenChange={setOpen}
      />
    </>
  );
}
