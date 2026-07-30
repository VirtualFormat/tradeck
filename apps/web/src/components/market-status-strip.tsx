/**
 * 市场状态条（client 组件）：US/HK/CN 开闭市状态 + 数据日期 + 开/闭市倒计时
 * - 时段按市场当地时间（周一至周五）：CN 09:30-15:00、HK 09:30-16:00、US 09:30-16:00
 * - 时区换算用 Intl timeZone（美股夏令时自动正确）；节假日不处理（仅排除周末）
 */
"use client";

import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

interface MarketDef {
  key: "US" | "HK" | "CN";
  timeZone: string;
  openMin: number; // 开盘（当地分钟）
  closeMin: number; // 收盘（当地分钟）
}

const MARKETS: MarketDef[] = [
  { key: "US", timeZone: "America/New_York", openMin: 9 * 60 + 30, closeMin: 16 * 60 },
  { key: "HK", timeZone: "Asia/Hong_Kong", openMin: 9 * 60 + 30, closeMin: 16 * 60 },
  { key: "CN", timeZone: "Asia/Shanghai", openMin: 9 * 60 + 30, closeMin: 15 * 60 },
];

/** 市场当地时间的「今天零点后分钟数 + 星期几」（Intl 换算，不写死 UTC 偏移） */
function marketLocal(timeZone: string, now: Date): { minutes: number; day: number } {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone,
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
  return { minutes: hour * 60 + Number(get("minute")), day: dayMap[get("weekday")] ?? 1 };
}

interface Status {
  text: string; // 状态文案（含倒计时）
  open: boolean; // 是否开盘中
}

function calcStatus(m: MarketDef, now: Date): Status {
  const { minutes, day } = marketLocal(m.timeZone, now);
  const isWeekday = day >= 1 && day <= 5;

  const fmt = (mins: number) => {
    const h = Math.floor(mins / 60);
    const mm = mins % 60;
    return `${h}:${String(mm).padStart(2, "0")}`;
  };

  if (isWeekday && minutes >= m.openMin && minutes < m.closeMin) {
    return { text: `开盘中 · 距收盘 ${fmt(m.closeMin - minutes)}`, open: true };
  }
  if (isWeekday && minutes < m.openMin) {
    return { text: `未开盘 · 距开盘 ${fmt(m.openMin - minutes)}`, open: false };
  }
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
    <div className={cn("ml-auto flex items-center gap-2", className)}>
      {shown.map((m) => {
        const s = now ? calcStatus(m, now) : null;
        return (
          <Badge
            key={m.key}
            variant="secondary"
            className={cn(
              "gap-1.5",
              // 开盘中用 accent 主题色调，非开盘沿用 secondary 灰
              s?.open && "border-accent/50 bg-accent/10 text-accent"
            )}
          >
            <span
              className="inline-block h-1.5 w-1.5 shrink-0 rounded-full"
              style={{
                backgroundColor: s?.open ? "var(--color-up)" : "var(--fg-dim)",
              }}
            />
            <span className="font-medium">{m.key}</span>
            {s && <span className="tab-nums font-normal opacity-80">{s.text}</span>}
            {dates[m.key] && (
              <span className="font-normal opacity-60">· {dates[m.key]}</span>
            )}
          </Badge>
        );
      })}
    </div>
  );
}
