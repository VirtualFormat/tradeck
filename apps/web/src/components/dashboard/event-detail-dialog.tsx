"use client";

import type { ReactNode } from "react";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Separator } from "@/components/ui/separator";
import { cn } from "@/lib/utils";

export type EventImportance = "high" | "medium" | "low" | "earnings";

export interface EventCenterItem {
  id: string;
  badge: string;
  title: string;
  importance: string;
  importanceLevel: EventImportance;
  kind: "economic" | "earnings";
  date: string | null;
  time: string | null;
  country: string | null;
  actual: string | null;
  forecast: string | null;
  previous: string | null;
  source: string | null;
  symbol: string | null;
  epsEstimate: number | null;
  session: string | null;
}

function sourceLabel(source: string | null): string {
  if (source === "baidu") return "百度财经（经 AkShare）";
  if (source === "fred") return "FRED（经 OpenBB）";
  if (source === "yfinance") return "Yahoo Finance（yfinance）";
  return source || "未标注";
}

function displayValue(value: string | number | null): string {
  if (value == null || value === "") return "—";
  return String(value);
}

function DetailItem({
  label,
  value,
}: {
  label: string;
  value: string | number | null;
}) {
  return (
    <div className="rounded-lg bg-secondary px-3 py-2.5">
      <dt className="text-[10px] text-muted-foreground">{label}</dt>
      <dd className="mt-1 break-words text-xs font-medium text-foreground">
        {displayValue(value)}
      </dd>
    </div>
  );
}

export function EventDetailDialog({
  item,
  children,
  triggerClassName,
}: {
  item: EventCenterItem;
  children: ReactNode;
  triggerClassName?: string;
}) {
  const isEarnings = item.kind === "earnings";

  return (
    <Dialog>
      <DialogTrigger
        render={
          <Button
            variant="ghost"
            className={cn(
              "h-auto w-full justify-start rounded-none px-0 py-1 text-left font-normal",
              triggerClassName
            )}
          />
        }
      >
        {children}
      </DialogTrigger>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <div className="flex flex-wrap items-center gap-2 pr-8">
            <Badge variant="secondary">{item.badge}</Badge>
            <Badge variant="outline">{item.importance}</Badge>
          </div>
          <DialogTitle className="leading-6">{item.title}</DialogTitle>
          <DialogDescription>
            {isEarnings ? "财报披露日历详情" : "宏观经济日历详情"}
          </DialogDescription>
        </DialogHeader>

        <Separator />

        {isEarnings ? (
          <dl className="grid grid-cols-2 gap-2">
            <DetailItem label="股票代码" value={item.symbol} />
            <DetailItem label="披露日期" value={item.date} />
            <DetailItem label="披露时段" value={item.session} />
            <DetailItem label="EPS 预期" value={item.epsEstimate} />
          </dl>
        ) : (
          <dl className="grid grid-cols-2 gap-2">
            <DetailItem label="日期" value={item.date} />
            <DetailItem label="时间" value={item.time} />
            <DetailItem label="国家 / 地区" value={item.country} />
            <DetailItem label="重要性" value={item.importance} />
            <DetailItem label="前值" value={item.previous} />
            <DetailItem label="预期" value={item.forecast} />
            <DetailItem label="实际值" value={item.actual} />
            <DetailItem label="数据来源" value={sourceLabel(item.source)} />
          </dl>
        )}

        {isEarnings ? (
          <>
            <Separator />
            <div className="text-xs text-muted-foreground">
              数据来源：{sourceLabel(item.source)}
            </div>
            {item.symbol ? (
              <DialogFooter>
                <Button render={<Link href={`/stocks/${item.symbol}`} />}>
                  查看个股详情
                </Button>
              </DialogFooter>
            ) : null}
          </>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}
