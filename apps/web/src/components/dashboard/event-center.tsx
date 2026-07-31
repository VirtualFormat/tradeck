import { EventCenterTabs } from "@/components/dashboard/event-center-tabs";
import type {
  EventCenterItem,
  EventImportance,
} from "@/components/dashboard/event-center-tabs";
import { EventDetailDialog } from "@/components/dashboard/event-detail-dialog";
import { EmptyState } from "@/components/empty-state";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  fetchEarningsCalendar,
  fetchEconomicCalendar,
} from "@/lib/openbb";
import type {
  EarningsCalendarItem,
  EconomicCalendarItem,
} from "@/lib/openbb";
import { cn } from "@/lib/utils";

const BEIJING_TIME_ZONE = "Asia/Shanghai";
const MAX_EVENT_ROWS = 5;
const MAX_WEEK_HIGHLIGHTS = 4;

interface NormalizedImportance {
  label: string;
  level: EventImportance;
  rank: number;
}

function beijingDateKey(): string {
  const parts = new Intl.DateTimeFormat("zh-CN", {
    timeZone: BEIJING_TIME_ZONE,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(new Date());
  const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${values.year}-${values.month}-${values.day}`;
}

function addDays(dateKey: string, days: number): string {
  const date = new Date(`${dateKey}T00:00:00.000Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

function shortDate(dateKey: string | null): string {
  return dateKey ? dateKey.slice(5) : "待定";
}

function normalizeImportance(value: string | null): NormalizedImportance {
  const normalized = value?.trim().toLowerCase();
  if (normalized === "高" || normalized === "high" || normalized === "3") {
    return { label: "高", level: "high", rank: 0 };
  }
  if (
    normalized === "中" ||
    normalized === "medium" ||
    normalized === "2"
  ) {
    return { label: "中", level: "medium", rank: 1 };
  }
  return { label: value?.trim() || "低", level: "low", rank: 2 };
}

function isMidOrHigh(value: string | null): boolean {
  return normalizeImportance(value).rank <= 1;
}

function eventTitle(event: EconomicCalendarItem): string {
  const name = event.event_name?.trim() ?? "";
  const country = event.country?.trim();
  if (!country || name.includes(country)) return name;
  return `${country} ${name}`;
}

function sessionLabel(session: string | null): string {
  const normalized = session?.trim().toUpperCase();
  if (normalized === "BMO") return "盘前";
  if (normalized === "AMC") return "盘后";
  return "待定";
}

function economicItem(
  event: EconomicCalendarItem,
  index: number,
  badge: string
): EventCenterItem {
  const importance = normalizeImportance(event.importance);
  return {
    id: `economic-${event.event_date}-${event.event_time}-${event.event_name}-${index}`,
    badge,
    title: eventTitle(event),
    importance: importance.label,
    importanceLevel: importance.level,
    kind: "economic",
    date: event.event_date,
    time: event.event_time,
    country: event.country,
    actual: event.actual,
    forecast: event.forecast,
    previous: event.previous,
    source: event.source,
    symbol: null,
    epsEstimate: null,
    session: null,
  };
}

function earningsItem(
  earning: EarningsCalendarItem,
  index: number,
  includeDate: boolean
): EventCenterItem {
  const session = sessionLabel(earning.session);
  return {
    id: `earnings-${earning.report_date}-${earning.symbol}-${index}`,
    badge: includeDate
      ? `${shortDate(earning.report_date)} ${session}`
      : session,
    title: `${earning.symbol} 财报`,
    importance: "财报",
    importanceLevel: "earnings",
    kind: "earnings",
    date: earning.report_date,
    time: null,
    country: null,
    actual: null,
    forecast: null,
    previous: null,
    source: earning.source,
    symbol: earning.symbol,
    epsEstimate: earning.eps_estimate,
    session,
  };
}

function sortEconomic(
  a: EconomicCalendarItem,
  b: EconomicCalendarItem
): number {
  const importance =
    normalizeImportance(a.importance).rank -
    normalizeImportance(b.importance).rank;
  if (importance !== 0) return importance;
  const date = (a.event_date ?? "").localeCompare(b.event_date ?? "");
  if (date !== 0) return date;
  return (a.event_time ?? "").localeCompare(b.event_time ?? "");
}

function highlightImportanceClass(level: EventImportance): string {
  if (level === "high") return "text-warn";
  if (level === "medium") return "text-fg-dim";
  return "text-muted-foreground";
}

function WeeklyHighlights({ events }: { events: EconomicCalendarItem[] }) {
  const highlights = events
    .filter((event) => event.event_date && event.event_name)
    .sort(sortEconomic)
    .slice(0, MAX_WEEK_HIGHLIGHTS);

  return (
    <Card size="sm" className="gap-1.5 py-3 shadow-none">
      <CardHeader className="px-3.5">
        <CardTitle className="text-xs font-semibold text-fg-dim">
          本周重点
        </CardTitle>
      </CardHeader>
      <CardContent className="px-3.5">
        {highlights.length > 0 ? (
          <div className="flex flex-col">
            {highlights.map((event, index) => {
              const item = economicItem(
                event,
                index,
                shortDate(event.event_date)
              );
              return (
                <EventDetailDialog
                  key={`${event.event_date}-${event.event_name}-${index}`}
                  item={item}
                  triggerClassName="min-h-7 border-b border-border/60 last:border-b-0"
                >
                  <span className="flex w-full min-w-0 items-center gap-2">
                    <Badge
                      variant="secondary"
                      className="h-4 shrink-0 rounded-sm px-1.5 py-0 font-mono text-[10px] font-medium tabular-nums"
                    >
                      {shortDate(event.event_date)}
                    </Badge>
                    <span className="min-w-0 flex-1 truncate text-xs text-foreground">
                      {eventTitle(event)}
                    </span>
                    <span
                      className={cn(
                        "shrink-0 text-[11px] font-medium",
                        highlightImportanceClass(item.importanceLevel)
                      )}
                    >
                      {item.importance}
                    </span>
                  </span>
                </EventDetailDialog>
              );
            })}
          </div>
        ) : (
          <EmptyState
            compact
            title="本周暂无重点事件"
            className="min-h-24 justify-center"
          />
        )}
      </CardContent>
    </Card>
  );
}

export async function EventCenter() {
  const [economicEvents, earnings] = await Promise.all([
    fetchEconomicCalendar(7).catch(() => [] as EconomicCalendarItem[]),
    fetchEarningsCalendar(14).catch(() => [] as EarningsCalendarItem[]),
  ]);

  const today = beijingDateKey();
  const weekEnd = addDays(today, 6);

  const todayEconomic = economicEvents
    .filter(
      (event) =>
        event.event_date === today &&
        Boolean(event.event_name?.trim()) &&
        isMidOrHigh(event.importance)
    )
    .sort(sortEconomic);
  const todayEarnings = earnings
    .filter(
      (earning) =>
        earning.report_date === today && Boolean(earning.symbol?.trim())
    )
    .sort((a, b) => a.symbol.localeCompare(b.symbol));

  const todayHigh = todayEconomic.filter(
    (event) => normalizeImportance(event.importance).rank === 0
  );
  const todayMedium = todayEconomic.filter(
    (event) => normalizeImportance(event.importance).rank === 1
  );
  const todayItems = [
    ...todayHigh.map((event, index) =>
      economicItem(event, index, event.event_time?.trim() || "全天")
    ),
    ...todayEarnings.map((earning, index) =>
      earningsItem(earning, index, false)
    ),
    ...todayMedium.map((event, index) =>
      economicItem(event, index, event.event_time?.trim() || "全天")
    ),
  ].slice(0, MAX_EVENT_ROWS);

  const weekEconomic = economicEvents
    .filter(
      (event) =>
        Boolean(event.event_name?.trim()) &&
        event.event_date != null &&
        event.event_date >= today &&
        event.event_date <= weekEnd &&
        isMidOrHigh(event.importance)
    )
    .sort(sortEconomic);

  const weekItems = weekEconomic
    .map((event, index) =>
      economicItem(event, index, shortDate(event.event_date))
    )
    .slice(0, MAX_EVENT_ROWS);

  const earningsItems = earnings
    .filter(
      (earning) =>
        Boolean(earning.symbol?.trim()) &&
        earning.report_date != null &&
        earning.report_date >= today
    )
    .sort((a, b) => {
      const date = (a.report_date ?? "").localeCompare(b.report_date ?? "");
      if (date !== 0) return date;
      return a.symbol.localeCompare(b.symbol);
    })
    .map((earning, index) => earningsItem(earning, index, true))
    .slice(0, MAX_EVENT_ROWS);

  return (
    <>
      <Card size="sm" className="gap-1.5 py-3 shadow-none">
        <CardContent className="px-3.5">
          <EventCenterTabs
            today={todayItems}
            week={weekItems}
            earnings={earningsItems}
          />
        </CardContent>
      </Card>
      <WeeklyHighlights events={weekEconomic} />
    </>
  );
}
