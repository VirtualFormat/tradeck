import { Card, CardContent } from "@/components/ui/card";
import { fmtDataDate, fmtPct, fmtPrice } from "@/lib/format";
import { cn } from "@/lib/utils";

interface CompactIndexCardProps {
  name: string;
  price: number | null;
  changePct: number | null;
  date: string | null;
}

/** 首页专用的无图表指数卡，详情页继续使用原 IndexCard。 */
export function CompactIndexCard({
  name,
  price,
  changePct,
  date,
}: CompactIndexCardProps) {
  const changeClass =
    changePct == null || changePct === 0
      ? "text-muted-foreground"
      : changePct > 0
        ? "text-up"
        : "text-down";

  return (
    <Card size="sm" className="min-h-[84px] gap-0 py-2.5">
      <CardContent className="flex min-w-0 flex-col gap-0.5 px-3">
        <div className="flex min-w-0 items-center justify-between gap-2 text-[11px] text-muted-foreground">
          <span className="truncate">{name}</span>
          <span className="shrink-0 tabular-nums">
            {fmtDataDate(date) ?? "—"}
          </span>
        </div>
        <span className="text-base leading-5 font-semibold text-foreground tabular-nums">
          {fmtPrice(price)}
        </span>
        <span
          className={cn(
            "text-[11px] leading-3.5 font-medium tabular-nums",
            changeClass
          )}
        >
          {fmtPct(changePct)}
        </span>
      </CardContent>
    </Card>
  );
}
