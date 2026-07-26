/**
 * 股票搜索框（客户端组件）
 * 输入代码跳转到 /stocks/[symbol]
 */
"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { MagnifyingGlassIcon } from "@phosphor-icons/react";

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
      <MagnifyingGlassIcon className="absolute left-3 h-4 w-4 text-muted-foreground" />
      <Input
        type="text"
        value={symbol}
        onChange={(e) => setSymbol(e.target.value)}
        placeholder="输入股票代码（如 AAPL, 600519.SH, 00700.HK）"
        className="pl-9 w-64"
      />
      <Button
        type="submit"
        variant="default"
        size="icon"
        className="ml-2"
      >
        <MagnifyingGlassIcon />
      </Button>
    </form>
  );
}
