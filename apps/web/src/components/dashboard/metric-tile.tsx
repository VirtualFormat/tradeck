import { cn } from "@/lib/utils";

interface MetricTileProps {
  label: string;
  value: string;
  meta?: string | null;
  detail?: string | null;
  metaClassName?: string;
  className?: string;
  valueClassName?: string;
}

/**
 * 首页指标带的紧凑数值单元。
 * 仅负责排版；数值单位、方向色和数据口径由调用方明确传入。
 */
export function MetricTile({
  label,
  value,
  meta,
  detail,
  metaClassName,
  className,
  valueClassName,
}: MetricTileProps) {
  return (
    <div
      className={cn(
        "flex min-w-0 flex-col gap-0.5 rounded-lg bg-secondary px-2.5 py-2",
        className
      )}
    >
      <span className="truncate text-[10px] leading-3 text-muted-foreground">
        {label}
      </span>
      <span
        className={cn(
          "text-xs leading-5 font-semibold whitespace-nowrap text-foreground tabular-nums xl:text-sm 2xl:text-[15px]",
          valueClassName
        )}
      >
        {value}
      </span>
      {(meta || detail) && (
        <div className="flex min-w-0 items-center justify-between gap-1 text-[10px] leading-3">
          <span
            className={cn(
              "truncate font-medium text-muted-foreground tabular-nums",
              metaClassName
            )}
          >
            {meta}
          </span>
          {detail && (
            <span className="shrink-0 text-muted-foreground tabular-nums">
              {detail}
            </span>
          )}
        </div>
      )}
    </div>
  );
}
