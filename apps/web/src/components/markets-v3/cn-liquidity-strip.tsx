import { Card, CardContent } from "@/components/ui/card";
import type { MarketBreadth } from "@/lib/openbb";
import { cn } from "@/lib/utils";

interface MetricItem {
  label: string;
  value: string;
  note: string;
  noteTone?: "up" | "down" | "warn" | "muted";
}

function metricTone(tone: MetricItem["noteTone"]) {
  if (tone === "up") return "text-up";
  if (tone === "down") return "text-down";
  if (tone === "warn") return "text-warn";
  return "text-muted-foreground";
}

function formatCount(value: number | null | undefined) {
  return value == null ? "—" : value.toLocaleString("zh-CN");
}

export function CnLiquidityStrip({
  breadth,
}: {
  breadth?: MarketBreadth | null;
}) {
  const metrics: MetricItem[] = [
    {
      label: "沪深成交额",
      value: "—",
      note: "暂无可靠数据",
      noteTone: "muted",
    },
    {
      label: "5日均量比",
      value: "—",
      note: "暂无可靠数据",
      noteTone: "muted",
    },
    {
      label: "真实涨停",
      value: formatCount(breadth?.real_limit_up_count),
      note:
        breadth?.real_limit_down_count == null
          ? "真实跌停 —"
          : `真实跌停 ${formatCount(breadth.real_limit_down_count)}`,
      noteTone: "down",
    },
    {
      label: "活跃度",
      value:
        breadth?.activity_rate == null
          ? "—"
          : `${breadth.activity_rate.toFixed(2)}%`,
      note:
        breadth?.activity_rate == null
          ? "等待宽度数据"
          : breadth.activity_rate >= 50
            ? "偏强"
            : breadth.activity_rate >= 35
              ? "中性"
              : "偏弱",
      noteTone:
        breadth?.activity_rate == null
          ? "muted"
          : breadth.activity_rate >= 50
            ? "up"
            : breadth.activity_rate >= 35
              ? "warn"
              : "down",
    },
  ];

  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
      {metrics.map((metric) => (
        <Card key={metric.label} size="sm" className="gap-0 py-0 shadow-none">
          <CardContent className="flex min-h-[76px] flex-col justify-center px-3 py-2.5">
            <p className="text-[10px] text-muted-foreground">{metric.label}</p>
            <p className="mt-0.5 text-base font-semibold tabular-nums text-foreground">
              {metric.value}
            </p>
            <p
              className={cn(
                "mt-0.5 text-[10px] font-medium",
                metricTone(metric.noteTone)
              )}
            >
              {metric.note}
            </p>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
