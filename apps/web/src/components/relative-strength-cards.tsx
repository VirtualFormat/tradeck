/**
 * 市场内部结构（服务端组件）
 * 4 组相对强弱比值卡片：RSP/SPY、IWM/SPY、QQQ/IVE、XLK/XLP
 */
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { EmptyState } from "@/components/empty-state";
import { RelativeStrengthSpark } from "@/components/relative-strength-spark";
import { fetchMarketInternals } from "@/lib/openbb";
import { cn } from "@/lib/utils";

function ChangeText({ value, label }: { value: number | null; label: string }) {
  return (
    <span className="text-xs text-muted-foreground">
      {label}{" "}
      {value == null ? (
        "—"
      ) : (
        <span
          className={cn(
            "tabular-nums",
            value > 0 && "text-up",
            value < 0 && "text-down"
          )}
        >
          {value > 0 ? "+" : ""}
          {value.toFixed(2)}%
        </span>
      )}
    </span>
  );
}

export async function RelativeStrengthCards() {
  const internals = await fetchMarketInternals(180);

  if (internals.length === 0) {
    return (
      <Card
        size="sm"
        className="@container/card bg-linear-to-t from-primary/5 to-card shadow-xs dark:bg-card"
      >
        <CardContent>
          <EmptyState compact title="无数据" />
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
      {internals.map((item) => (
        <Card
          key={item.pair}
          size="sm"
          className="@container/card bg-linear-to-t from-primary/5 to-card shadow-xs dark:bg-card"
        >
          <CardHeader>
            <CardTitle className="text-base font-medium">
              {item.pair}
              <span className="ml-1.5 text-xs font-normal text-muted-foreground">
                {item.label}
              </span>
            </CardTitle>
            <CardDescription>{item.note}</CardDescription>
          </CardHeader>
          <CardContent className="space-y-2">
            <div className="flex items-baseline gap-3">
              <span className="text-xl font-semibold tabular-nums">
                {item.current.toFixed(3)}
              </span>
              <ChangeText value={item.chg_1m} label="1M" />
              <ChangeText value={item.chg_3m} label="3M" />
            </div>
            <RelativeStrengthSpark data={item.series} />
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
