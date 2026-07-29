/**
 * 今日事件（首页侧栏）
 * 数据：fetchEconomicCalendar —— 复用 /macro 页宏观数据日历的 fetcher
 * 展示今日（本地时区）宏观事件，高重要度优先；每行：时间 tag + 名称 + 重要度
 * 无数据走 EmptyState（优雅降级，不造假）
 */
import { fetchEconomicCalendar } from "@/lib/openbb";
import type { EconomicCalendarItem } from "@/lib/openbb";
import { fmtDataDate } from "@/lib/format";
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/empty-state";
import Link from "next/link";

/** 重要性着色：高=橙（重点关注 text-warn），其余灰 */
function importanceClass(importance: string | null): string {
  if (importance === "高" || importance === "high") return "text-warn";
  if (importance === "中" || importance === "medium") return "text-fg-dim";
  return "text-muted-foreground";
}

/** 重要度排序权重：高 > 中 > 其他 */
function importanceRank(importance: string | null): number {
  if (importance === "高" || importance === "high") return 0;
  if (importance === "中" || importance === "medium") return 1;
  return 2;
}

/** 只保留中/高重要度（滤掉「低」的库存/拍卖等噪音行；null 视为低） */
function isMidOrHigh(importance: string | null): boolean {
  return (
    importance === "高" ||
    importance === "high" ||
    importance === "中" ||
    importance === "medium"
  );
}

/** 本地今日 YYYY-MM-DD */
function todayKey(): string {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

export async function TodayEvents() {
  const all = await fetchEconomicCalendar(7).catch(
    () => [] as EconomicCalendarItem[]
  );
  const key = todayKey();
  // 仅保留今日、中/高重要度事件；高重要度优先，其次按时间升序
  const events = all
    .filter((e) => e.event_date === key && e.event_name && isMidOrHigh(e.importance))
    .sort((a, b) => {
      const r = importanceRank(a.importance) - importanceRank(b.importance);
      if (r !== 0) return r;
      return (a.event_time ?? "").localeCompare(b.event_time ?? "");
    });

  // 数据日期以今日为准
  const dateLabel = fmtDataDate(key);

  return (
    <Card
      size="sm"
      className="@container/card bg-linear-to-t from-primary/5 to-card shadow-xs dark:bg-card"
    >
      <CardHeader>
        <CardTitle className="text-base font-medium text-fg-dim">
          今日事件
        </CardTitle>
        {dateLabel && (
          <CardDescription className="text-xs text-muted-foreground">
            {dateLabel}
          </CardDescription>
        )}
        <CardAction>
          <Link
            href="/macro"
            className="text-xs text-muted-foreground hover:text-fg"
          >
            更多 →
          </Link>
        </CardAction>
      </CardHeader>
      <CardContent>
        {events.length > 0 ? (
          <ScrollArea className="max-h-56">
            <div className="flex flex-col">
              {events.map((e, i) => (
                <div
                  key={`${e.event_name}-${i}`}
                  className="flex items-start gap-2 border-b border-border/40 py-1.5 last:border-0"
                >
                  <Badge
                    variant="secondary"
                    className="tab-nums mt-0.5 shrink-0 rounded-sm px-1 py-0 text-[9px]"
                  >
                    {e.event_time ?? "全天"}
                  </Badge>
                  <span className="flex-1 text-xs leading-snug text-fg-dim">
                    {e.event_name}
                    {e.country && (
                      <span className="ml-1 text-muted-foreground">
                        · {e.country}
                      </span>
                    )}
                  </span>
                  {e.importance && (
                    <span
                      className={`shrink-0 text-[10px] ${importanceClass(
                        e.importance
                      )}`}
                    >
                      {e.importance}
                    </span>
                  )}
                </div>
              ))}
            </div>
          </ScrollArea>
        ) : (
          <EmptyState compact title="今日无事件" />
        )}
      </CardContent>
    </Card>
  );
}
