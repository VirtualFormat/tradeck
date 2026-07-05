/**
 * 股票搜索框（客户端组件）
 * 输入代码跳转到 /stocks/[symbol]
 */
"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Input } from "@/components/ui/input";
import { Search } from "lucide-react";

export function StockSearch() {
  const [symbol, setSymbol] = useState("");
  const router = useRouter();

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = symbol.trim().toUpperCase();
    if (!trimmed) return;
    router.push(`/stocks/${encodeURIComponent(trimmed)}`);
  }

  return (
    <form onSubmit={handleSubmit} className="relative flex items-center">
      <Search className="absolute left-3 h-4 w-4 text-muted" />
      <Input
        type="text"
        value={symbol}
        onChange={(e) => setSymbol(e.target.value)}
        placeholder="输入股票代码（如 AAPL, 600519.SS, 0700.HK）"
        className="pl-9 w-64"
      />
      <button
        type="submit"
        className="ml-2 rounded-md bg-accent px-3 py-1.5 text-xs font-medium text-white hover:bg-accent/80"
      >
        查询
      </button>
    </form>
  );
}
