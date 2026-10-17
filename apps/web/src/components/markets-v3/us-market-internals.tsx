import { EmptyState } from "@/components/empty-state";
import { MarketSummaryCard } from "@/components/markets-v3/market-summary-card";
import { Badge } from "@/components/ui/badge";
import type { MarketInternal } from "@/lib/openbb";
import { cn } from "@/lib/utils";

const PAIR_ORDER = ["RSP/SPY", "IWM/SPY", "QQQ/IVE", "XLK/XLP"];

function direction(value: number | null): string {
  if (value == null || value === 0) return "→";
  return value > 0 ? "↑" : "↓";
}

function directionClass(value: number | null): string {
  if (value == null || value === 0) return "text-muted-foreground";
  return value > 0 ? "text-up" : "text-down";
}

function shortNote(item: MarketInternal): string {
  if (item.chg_1m == null) return item.note;

  if (item.pair === "RSP/SPY") {
    return item.chg_1m > 0 ? "广度改善" : "权重股主导";
  }
  if (item.pair === "IWM/SPY") {
    return item.chg_1m > 0 ? "风险偏好扩散" : "小盘风险偏好收缩";
  }
  if (item.pair === "QQQ/IVE") {
    return item.chg_1m > 0 ? "成长风格占优" : "价值风格占优";
  }
  if (item.pair === "XLK/XLP") {
    return item.chg_1m > 0 ? "进攻板块占优" : "防御板块占优";
  }
  return item.note;
}

export function UsMarketInternals({ items }: { items: MarketInternal[] }) {
  const ordered = [...items].sort((a, b) => {
    const aIndex = PAIR_ORDER.indexOf(a.pair);
    const bIndex = PAIR_ORDER.indexOf(b.pair);
    return (aIndex === -1 ? 99 : aIndex) - (bIndex === -1 ? 99 : bIndex);
  });

  return (
    <MarketSummaryCard
      title="市场内部结构"
      description="相对强弱 · 近 1 月变化"
      action={
        <Badge variant="outline" className="text-[10px]">
          {ordered.length}/4 覆盖
        </Badge>
      }
      className="h-full xl:min-h-[210px]"
    >
      {ordered.length > 0 ? (
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-1 2xl:grid-cols-2">
          {ordered.map((item) => (
            <div
              key={item.pair}
              className="min-w-0 rounded-lg bg-secondary px-3 py-2"
            >
              <div className="flex min-w-0 items-center justify-between gap-2">
                <span className="truncate text-xs font-medium text-foreground">
                  {item.pair}
                  <span className="ml-1.5 text-[10px] font-normal text-muted-foreground">
                    {item.label}
                  </span>
                </span>
                <span
                  className={cn(
                    "shrink-0 text-xs font-semibold tabular-nums",
                    directionClass(item.chg_1m)
                  )}
                >
                  {direction(item.chg_1m)}
                  {item.chg_1m == null
                    ? "—"
                    : `${Math.abs(item.chg_1m).toFixed(2)}%`}
                </span>
              </div>
              <div className="mt-1 truncate text-[10px] text-muted-foreground">
                {shortNote(item)}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <EmptyState
          compact
          title="暂无市场内部结构"
          description="RSP/SPY、IWM/SPY 等比值恢复后自动更新"
          className="min-h-28 justify-center"
        />
      )}
    </MarketSummaryCard>
  );
}
