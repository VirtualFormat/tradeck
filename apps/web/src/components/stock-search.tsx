/**
 * 股票搜索框（客户端组件）
 * 支持代码 / 名称搜索（防抖请求 /api/search），选中或回车跳转 /stocks/[symbol]
 */
"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { MagnifyingGlassIcon } from "@phosphor-icons/react";

import { normalizeSymbol } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";

interface SearchResult {
  symbol: string;
  name: string | null;
  market: string;
}

const DEBOUNCE_MS = 300;

export function StockSearch() {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [open, setOpen] = useState(false);
  const router = useRouter();
  const seqRef = useRef(0);

  // 防抖搜索（最新一次请求生效，过期响应丢弃）
  useEffect(() => {
    const kw = query.trim();
    if (!kw) return;
    const seq = ++seqRef.current;
    const timer = setTimeout(async () => {
      try {
        const res = await fetch(`/api/search?q=${encodeURIComponent(kw)}`, {
          cache: "no-store",
        });
        const data = res.ok ? await res.json() : [];
        if (seqRef.current === seq) {
          setResults(Array.isArray(data) ? data : []);
          setOpen(true);
        }
      } catch {
        /* 降级：拉不到就不出建议 */
      }
    }, DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [query]);

  function go(symbol: string) {
    setQuery("");
    setOpen(false);
    router.push(`/stocks/${encodeURIComponent(symbol)}`);
  }

  function handleEnter() {
    const kw = query.trim();
    if (!kw) return;
    // 有建议选第一条；无建议按代码归一化直接跳（保留原裸码输入行为）
    go(results.length > 0 ? results[0].symbol : normalizeSymbol(kw));
  }

  return (
    <Command shouldFilter={false} className="relative w-72">
      <MagnifyingGlassIcon className="pointer-events-none absolute left-3 top-1/2 z-10 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
      <CommandInput
        value={query}
        onValueChange={(value) => {
          setQuery(value);
          if (!value.trim()) {
            setResults([]);
            setOpen(false);
          }
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            handleEnter();
          }
          if (e.key === "Escape") setOpen(false);
        }}
        onFocus={() => results.length > 0 && setOpen(true)}
        placeholder="输入代码或名称（如 AAPL、茅台）"
        className="pl-9"
      />
      {open && query.trim() && (
        <CommandList className="absolute top-11 z-50 max-h-72 w-full rounded-md border border-border bg-popover shadow-md">
          <CommandEmpty>无匹配标的</CommandEmpty>
          <CommandGroup>
            {results.map((r) => (
              <CommandItem
                key={r.symbol}
                value={r.symbol}
                onSelect={() => go(r.symbol)}
                className="flex items-center justify-between gap-2"
              >
                <span className="min-w-0 truncate">
                  <span className="tab-nums mr-2 font-medium">{r.symbol}</span>
                  <span className="text-muted-foreground">{r.name}</span>
                </span>
                <Badge variant="secondary" className="shrink-0">
                  {r.market}
                </Badge>
              </CommandItem>
            ))}
          </CommandGroup>
        </CommandList>
      )}
    </Command>
  );
}
