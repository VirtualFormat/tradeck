/**
 * 日期选择器（客户端组件）
 * - shadcn Popover + Calendar（react-day-picker）
 * - 选择后写 URL ?date=YYYY-MM-DD（清除参数=最近快照日）
 */
"use client";

import { useCallback, useState } from "react";
import { useRouter, usePathname, useSearchParams } from "next/navigation";
import { CalendarIcon, XIcon } from "@phosphor-icons/react";

import { Button } from "@/components/ui/button";
import { Calendar } from "@/components/ui/calendar";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";

function fmt(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

export function DatePicker() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const current = searchParams.get("date"); // YYYY-MM-DD | null
  const [open, setOpen] = useState(false);

  const handleSelect = useCallback(
    (d: Date | undefined) => {
      const params = new URLSearchParams(searchParams);
      if (d) {
        params.set("date", fmt(d));
      } else {
        params.delete("date");
      }
      const query = params.toString();
      router.push(query ? `${pathname}?${query}` : pathname, { scroll: false });
      setOpen(false);
    },
    [router, pathname, searchParams]
  );

  return (
    <div className="flex items-center gap-1">
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger
          render={
            <Button
              variant="outline"
              size="sm"
              className="gap-1.5 text-xs text-fg-dim"
            />
          }
        >
          <CalendarIcon className="size-3.5" />
          {current ?? "最近交易日"}
        </PopoverTrigger>
        <PopoverContent className="w-auto p-0" align="start">
          <Calendar
            mode="single"
            selected={current ? new Date(`${current}T00:00:00`) : undefined}
            onSelect={handleSelect}
            disabled={(date) => date > new Date()}
          />
        </PopoverContent>
      </Popover>
      {current && (
        <Button
          variant="ghost"
          size="icon-sm"
          onClick={() => handleSelect(undefined)}
          title="回到最近交易日"
        >
          <XIcon className="size-3" />
        </Button>
      )}
    </div>
  );
}
