/**
 * 本周经济日历（首页侧栏）
 * 数据：fetchEconomicCalendar —— 复用 /macro 页宏观数据日历的 fetcher
 * 展示未来 7 天宏观事件竖排：日期 tag + 事件 + 重要度；按日期→时间升序
 * 无数据走 EmptyState（优雅降级，不造假）
 */
import { fetchEconomicCalendar } from "@/lib/openbb";
import type { EconomicCalendarItem } from "@/lib/openbb";
import {
  Card,
  CardAction,
  CardContent,
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

/** 只保留中/高重要度（滤掉「低」的库存/拍卖等噪音行；null 视为低） */
function isMidOrHigh(importance: string | null): boolean {
  return (
    importance === "高" ||
    importance === "high" ||
    importance === "中" ||
    importance === "medium"
  );
}

/** 日历短日期：07-30 周四 */
function fmtCalDate(dateStr: string | null | undefined): string {
  if (!dateStr) return "—";
  const d = new Date(`${dateStr}T00:00:00`);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    weekday: "short",
  });
}

export async function EconCalendarWeek() {
  const all = await fetchEconomicCalendar(7).catch(
    () => [] as EconomicCalendarItem[]
  );
  // 有事件名、且中/高重要度的行，按日期→时间升序
  const events = all
    .filter((e) => e.event_name && isMidOrHigh(e.importance))
    .sort((a, b) => {
      const d = (a.event_date ?? "").localeCompare(b.event_date ?? "");
      if (d !== 0) return d;
      return (a.event_time ?? "").localeCompare(b.event_time ?? "");
    });

  return (
    <Card
      size="sm"
      className="@container/card bg-linear-to-t from-primary/5 to-card shadow-xs dark:bg-card"
    >
      <CardHeader>
        <CardTitle className="text-base font-medium text-fg-dim">
          本周经济日历
        </CardTitle>
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
          <ScrollArea className="max-h-72">
            <div className="flex flex-col">
              {events.map((e, i) => (
                <div
                  key={`${e.event_date}-${e.event_name}-${i}`}
                  className="flex items-start gap-2 border-b border-border/40 py-1.5 last:border-0"
                >
                  <Badge
                    variant="secondary"
                    className="tab-nums mt-0.5 shrink-0 rounded-sm px-1 py-0 text-[9px] whitespace-nowrap"
                  >
                    {fmtCalDate(e.event_date)}
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
          <EmptyState compact title="本周无事件" />
        )}
      </CardContent>
    </Card>
  );
}
