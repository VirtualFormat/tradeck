/**
 * 市场状态条（client 组件）：US/HK/CN 常规交易时段 + 行情截止日
 * - 时段按市场当地时间；CN/HK 包含午休，US 连续交易
 * - 时区换算用 Intl timeZone（美股夏令时自动正确）
 * - 没有交易所节假日日历，不推断节假日；行情新鲜度与开闭市状态分开显示
 */
"use client";

import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

interface MarketDef {
  key: "US" | "HK" | "CN";
  timeZone: string;
  sessions: readonly (readonly [number, number])[];
}

const MARKETS: MarketDef[] = [
  {
    key: "US",
    timeZone: "America/New_York",
    sessions: [[9 * 60 + 30, 16 * 60]],
  },
  {
    key: "HK",
    timeZone: "Asia/Hong_Kong",
    sessions: [
      [9 * 60 + 30, 12 * 60],
      [13 * 60, 16 * 60],
    ],
  },
  {
    key: "CN",
    timeZone: "Asia/Shanghai",
    sessions: [
      [9 * 60 + 30, 11 * 60 + 30],
      [13 * 60, 15 * 60],
    ],
  },
];

/** 市场当地时间的「今天零点后分钟数 + 星期几」（Intl 换算，不写死 UTC 偏移） */
function marketLocal(
  timeZone: string,
  now: Date
): { minutes: number; day: number; dateKey: string } {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "numeric",
    minute: "numeric",
    weekday: "short",
    hour12: false,
  }).formatToParts(now);
  const get = (t: string) => parts.find((p) => p.type === t)?.value ?? "";
  const hour = Number(get("hour")) % 24;
  const dayMap: Record<string, number> = {
    Sun: 0, Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6,
  };
  return {
    minutes: hour * 60 + Number(get("minute")),
    day: dayMap[get("weekday")] ?? 1,
    dateKey: `${get("year")}-${get("month")}-${get("day")}`,
  };
}

interface Status {
  text: string; // 状态文案（含倒计时）
  open: boolean; // 是否开盘中
}

interface DataRecency {
  label: string;
  needsUpdate: boolean;
}

function normalizeDateKey(
  latestDate: string | null | undefined,
  currentDateKey: string
): string | null {
  if (!latestDate) return null;
  const normalized = latestDate.trim();
  const fullDate = normalized.match(/^(\d{4}-\d{2}-\d{2})/)?.[1];
  if (fullDate) return fullDate;

  const shortDate = normalized.match(/^(\d{2}-\d{2})$/)?.[1];
  if (!shortDate) return null;
  const currentYear = Number(currentDateKey.slice(0, 4));
  const currentTime = Date.parse(`${currentDateKey}T00:00:00Z`);
  const thisYear = `${currentYear}-${shortDate}`;
  const thisYearTime = Date.parse(`${thisYear}T00:00:00Z`);
  return thisYearTime - currentTime > 180 * 86_400_000
    ? `${currentYear - 1}-${shortDate}`
    : thisYear;
}

function weekdayLag(latestDateKey: string, currentDateKey: string): number | null {
  const latestTime = Date.parse(`${latestDateKey}T00:00:00Z`);
  const currentTime = Date.parse(`${currentDateKey}T00:00:00Z`);
  if (!Number.isFinite(latestTime) || !Number.isFinite(currentTime)) return null;
  if (latestTime >= currentTime) return 0;

  let lag = 0;
  for (
    let cursor = latestTime + 86_400_000;
    cursor <= currentTime;
    cursor += 86_400_000
  ) {
    const weekday = new Date(cursor).getUTCDay();
    if (weekday >= 1 && weekday <= 5) lag += 1;
  }
  return lag;
}

function dataRecency(
  latestDate: string | null | undefined,
  currentDateKey: string
): DataRecency {
  const dateKey = normalizeDateKey(latestDate, currentDateKey);
  if (!dateKey) return { label: "行情截止 —", needsUpdate: true };
  const lag = weekdayLag(dateKey, currentDateKey);
  return {
    label: `行情截止 ${dateKey.slice(5)}`,
    needsUpdate: lag === null || lag > 1,
  };
}

function calcStatus(m: MarketDef, now: Date): Status {
  const { minutes, day } = marketLocal(m.timeZone, now);
  const isWeekday = day >= 1 && day <= 5;
  const firstSession = m.sessions[0];
  const lastSession = m.sessions[m.sessions.length - 1];

  const fmt = (mins: number) => {
    const h = Math.floor(mins / 60);
    const mm = mins % 60;
    return `${h}:${String(mm).padStart(2, "0")}`;
  };

  if (!isWeekday) {
    return { text: "周末休市", open: false };
  }

  if (minutes < firstSession[0]) {
    return {
      text: `未开盘 · 距开盘 ${fmt(firstSession[0] - minutes)}`,
      open: false,
    };
  }

  for (let index = 0; index < m.sessions.length; index += 1) {
    const [openMin, closeMin] = m.sessions[index];
    if (minutes >= openMin && minutes < closeMin) {
      return {
        text: `开盘中 · 距收盘 ${fmt(closeMin - minutes)}`,
        open: true,
      };
    }

    const nextSession = m.sessions[index + 1];
    if (nextSession && minutes >= closeMin && minutes < nextSession[0]) {
      return {
        text: `午间休市 · 距下午开盘 ${fmt(nextSession[0] - minutes)}`,
        open: false,
      };
    }
  }

  if (minutes >= lastSession[1]) return { text: "已收盘", open: false };
  return { text: "已收盘", open: false };
}

export function MarketStatusStrip({
  dates,
  className,
}: {
  // 只显示 dates 中出现的市场（单市场页只传一个 key，首页传三个）
  dates: Partial<Record<"US" | "HK" | "CN", string | null>>;
  className?: string;
}) {
  // null 初始态避免 SSR/客户端 hydration 时间不一致；挂载后再开始计时
  const [now, setNow] = useState<Date | null>(null);

  useEffect(() => {
    // 用 rAF 延后首次赋值（避免在 effect 体内同步 setState 触发级联渲染）
    const raf = requestAnimationFrame(() => setNow(new Date()));
    const timer = setInterval(() => setNow(new Date()), 30_000);
    return () => {
      cancelAnimationFrame(raf);
      clearInterval(timer);
    };
  }, []);

  // 仅渲染 dates 中存在的市场（单市场页只有一枚胶囊）
  const shown = MARKETS.filter((m) => m.key in dates);

  return (
    <div className={cn("ml-auto flex flex-wrap items-center gap-2", className)}>
      {shown.map((m) => {
        const local = now ? marketLocal(m.timeZone, now) : null;
        const s = now ? calcStatus(m, now) : null;
        const recency = local
          ? dataRecency(dates[m.key], local.dateKey)
          : null;
        return (
          <div key={m.key} className="flex items-center gap-1.5">
            <Badge
              variant="secondary"
              className={cn(
                "gap-1.5",
                s?.open && "border-up/30 bg-up/10 text-up"
              )}
            >
              <span
                className={cn(
                  "inline-block h-1.5 w-1.5 shrink-0 rounded-full",
                  s?.open ? "bg-up" : "bg-muted-foreground"
                )}
              />
              <span className="font-medium">{m.key}</span>
              {s && (
                <span className="tab-nums font-normal opacity-80">{s.text}</span>
              )}
            </Badge>
            {recency && (
              <Badge
                variant="outline"
                className={cn(
                  "tab-nums font-normal",
                  recency.needsUpdate &&
                    "border-warn/40 bg-warn/10 text-warn"
                )}
              >
                {recency.label}
                {recency.needsUpdate ? " · 数据待更新" : ""}
              </Badge>
            )}
          </div>
        );
      })}
    </div>
  );
}
