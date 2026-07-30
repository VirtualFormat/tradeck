import { cn } from "@/lib/utils";

interface MarketBreadthBarProps {
  up: number;
  flat: number;
  down: number;
  className?: string;
}

/**
 * 三段市场宽度条：红涨、灰平、绿跌。
 * 这是多值业务数据可视化，不使用只表达单值进度的 Progress。
 */
export function MarketBreadthBar({
  up,
  flat,
  down,
  className,
}: MarketBreadthBarProps) {
  const safeUp = Math.max(0, up);
  const safeFlat = Math.max(0, flat);
  const safeDown = Math.max(0, down);
  const total = safeUp + safeFlat + safeDown;

  if (total === 0) {
    return (
      <div
        role="img"
        aria-label="市场宽度暂无有效数据"
        className={cn("h-2 w-full rounded-full bg-muted", className)}
      />
    );
  }

  return (
    <div
      role="img"
      aria-label={`上涨 ${safeUp}，平盘 ${safeFlat}，下跌 ${safeDown}`}
      className={cn(
        "flex h-2 w-full max-w-[12.5rem] overflow-hidden rounded-full bg-muted",
        className
      )}
    >
      {safeUp > 0 ? (
        <div
          className="h-full bg-up"
          style={{ flexBasis: 0, flexGrow: safeUp }}
        />
      ) : null}
      {safeFlat > 0 ? (
        <div
          className="h-full bg-muted-foreground/25"
          style={{ flexBasis: 0, flexGrow: safeFlat }}
        />
      ) : null}
      {safeDown > 0 ? (
        <div
          className="h-full bg-down"
          style={{ flexBasis: 0, flexGrow: safeDown }}
        />
      ) : null}
    </div>
  );
}
