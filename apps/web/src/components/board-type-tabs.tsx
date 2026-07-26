/**
 * 板块类型切换器（客户端组件）
 * 通过 URL search params 切换 行业/概念
 */
"use client";

import { useRouter, usePathname, useSearchParams } from "next/navigation";
import { useCallback } from "react";

import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";

export type BoardType = "industry" | "concept";

const TYPES: { key: BoardType; label: string }[] = [
  { key: "industry", label: "行业板块" },
  { key: "concept", label: "概念板块" },
];

export function BoardTypeTabs() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const current = (searchParams.get("board") as BoardType) ?? "industry";

  const handleSwitch = useCallback(
    (type: BoardType) => {
      const params = new URLSearchParams(searchParams);
      if (type === "industry") {
        params.delete("board");
      } else {
        params.set("board", type);
      }
      const query = params.toString();
      router.push(query ? `${pathname}?${query}` : pathname, { scroll: false });
    },
    [router, pathname, searchParams]
  );

  return (
    <Tabs
      value={current}
      onValueChange={(v) => handleSwitch(v as BoardType)}
      className="flex-row gap-0"
    >
      <TabsList className="rounded-md border border-border bg-panel-2 p-0.5">
        {TYPES.map((t) => (
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
  );
}
