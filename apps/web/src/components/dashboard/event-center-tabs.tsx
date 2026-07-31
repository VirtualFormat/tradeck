"use client";

import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/empty-state";
import {
  EventDetailDialog,
  type EventCenterItem,
  type EventImportance,
} from "@/components/dashboard/event-detail-dialog";
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs";
import { cn } from "@/lib/utils";

export type { EventCenterItem, EventImportance };

interface EventCenterTabsProps {
  today: EventCenterItem[];
  week: EventCenterItem[];
  earnings: EventCenterItem[];
}

function importanceClass(level: EventImportance): string {
  if (level === "high" || level === "earnings") return "text-warn";
  if (level === "medium") return "text-fg-dim";
  return "text-muted-foreground";
}

function EventList({
  items,
  emptyTitle,
}: {
  items: EventCenterItem[];
  emptyTitle: string;
}) {
  if (items.length === 0) {
    return (
      <EmptyState
        compact
        title={emptyTitle}
        className="min-h-[7.75rem] justify-center"
      />
    );
  }

  return (
    <div className="flex flex-col">
      {items.map((item) => (
        <EventDetailDialog
          key={item.id}
          item={item}
          triggerClassName="min-h-7 border-b border-border/60 last:border-b-0"
        >
          <span className="flex w-full min-w-0 items-center gap-2">
            <Badge
              variant="secondary"
              className="h-4 max-w-20 shrink-0 rounded-sm px-1.5 py-0 font-mono text-[10px] font-medium tabular-nums"
            >
              <span className="truncate">{item.badge}</span>
            </Badge>
            <span className="min-w-0 flex-1 truncate text-xs text-foreground">
              {item.title}
            </span>
            <span
              className={cn(
                "shrink-0 text-[11px] font-medium",
                importanceClass(item.importanceLevel)
              )}
            >
              {item.importance}
            </span>
          </span>
        </EventDetailDialog>
      ))}
    </div>
  );
}

export function EventCenterTabs({
  today,
  week,
  earnings,
}: EventCenterTabsProps) {
  return (
    <Tabs defaultValue="today" className="gap-1.5">
      <div className="flex h-5 min-w-0 items-center gap-2">
        <span className="shrink-0 text-xs font-semibold text-fg-dim">
          事件中心
        </span>
        <TabsList
          variant="default"
          aria-label="事件范围"
          className="ml-auto h-5 gap-0.5 rounded-md bg-transparent p-0"
        >
          <TabsTrigger
            value="today"
            className="h-5 min-w-0 rounded-[5px] px-2 text-[10px] font-semibold data-active:bg-secondary data-active:shadow-none dark:data-active:border-transparent dark:data-active:bg-secondary"
          >
            今天
          </TabsTrigger>
          <TabsTrigger
            value="week"
            className="h-5 min-w-0 rounded-[5px] px-2 text-[10px] font-semibold data-active:bg-secondary data-active:shadow-none dark:data-active:border-transparent dark:data-active:bg-secondary"
          >
            本周
          </TabsTrigger>
          <TabsTrigger
            value="earnings"
            className="h-5 min-w-0 rounded-[5px] px-2 text-[10px] font-semibold data-active:bg-secondary data-active:shadow-none dark:data-active:border-transparent dark:data-active:bg-secondary"
          >
            财报
          </TabsTrigger>
        </TabsList>
        <span className="shrink-0 text-[10px] font-medium text-muted-foreground">
          来源时间
        </span>
      </div>

      <TabsContent value="today">
        <EventList items={today} emptyTitle="今日暂无事件" />
      </TabsContent>
      <TabsContent value="week">
        <EventList items={week} emptyTitle="本周暂无重点事件" />
      </TabsContent>
      <TabsContent value="earnings">
        <EventList items={earnings} emptyTitle="近期暂无财报" />
      </TabsContent>
    </Tabs>
  );
}
