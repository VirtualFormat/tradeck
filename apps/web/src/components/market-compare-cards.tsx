/**
 * 三市对比总览卡（首页用，服务端组件）
 * 一行三卡（CN / US / HK），数据来自 backend /api/market-summary（market_breadth 最新行）：
 * - 标题行：市场名 Badge + 日期与来源（CN 显「乐咕」实时口径，US/HK 显「日K」全市场口径）——时间口径差异可见
 * - 宽度条：复用 advance-decline-chart 的涨/跌/平半环
 * - 涨跌停行：仅 CN（limit_up/limit_down 非 null 才显）
 * - 上涨占比行：up_ratio × 100 + ui/progress
 * - 空数据走 EmptyState
 * 支持首页 DatePicker 的 ?date= 传入（快照回看历史）。
 */
import {
  Card,
  CardAction,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { EmptyState } from "@/components/empty-state";
import { AdvanceDeclineChart } from "@/components/advance-decline-chart";
import { fetchMarketSummary, type MarketSummary } from "@/lib/openbb";
import { fmtDataDate } from "@/lib/format";

// 市场展示定义（渲染顺序 CN → US → HK）
const MARKET_DEFS: Array<{
  market: string;
  label: string;
  source: string; // 数据来源口径标注
}> = [
  { market: "CN", label: "A股", source: "乐咕" },
  { market: "US", label: "美股", source: "日K" },
  { market: "HK", label: "港股", source: "日K" },
];

function CompareCard({
  label,
  source,
  data,
}: {
  label: string;
  source: string;
  data: MarketSummary | undefined;
}) {
  const dateLabel = fmtDataDate(data?.date ?? null);
  const hasData =
    data != null && (data.up > 0 || data.down > 0 || data.flat > 0);
  const upPct =
    data?.up_ratio != null ? Math.round(data.up_ratio * 100) : null;
  const showLimit =
    data != null && data.limit_up != null && data.limit_down != null;

  return (
    <Card
      size="sm"
      className="@container/card bg-linear-to-t from-primary/5 to-card shadow-xs dark:bg-card"
    >
      <CardHeader>
        <CardTitle className="text-base font-medium text-fg-dim">
          <Badge variant="outline">{label}</Badge>
        </CardTitle>
        <CardAction className="text-xs text-muted-foreground">
          {dateLabel ? `${dateLabel} · ${source}` : source}
        </CardAction>
      </CardHeader>
      <CardContent>
        {hasData ? (
          <div className="flex flex-col gap-3">
            {/* 涨跌平宽度条（半环） */}
            <AdvanceDeclineChart
              data={{ up: data.up, down: data.down, flat: data.flat }}
            />

            {/* 涨跌停行：仅 CN（legu 口径，limit 非 null 才显） */}
            {showLimit ? (
              <div className="flex items-center justify-center gap-4 text-xs tabular-nums">
                <span className="text-up">涨停 {data.limit_up}</span>
                <span className="text-down">跌停 {data.limit_down}</span>
              </div>
            ) : null}

            {/* 上涨占比 */}
            <div className="flex flex-col gap-1">
              <div className="flex items-center justify-between text-xs text-muted-foreground">
                <span>上涨占比</span>
                <span className="tabular-nums text-fg-dim">
                  {upPct != null ? `${upPct}%` : "—"}
                </span>
              </div>
              <Progress value={upPct ?? 0} />
            </div>
          </div>
        ) : (
          <EmptyState compact title="无数据" className="h-[180px] w-full" />
        )}
      </CardContent>
    </Card>
  );
}

export async function MarketCompareCards({ date }: { date?: string }) {
  const summary = await fetchMarketSummary(date);
  const byMarket = new Map(summary.map((s) => [s.market, s]));

  return (
    <section>
      <h2 className="mb-3 text-sm font-medium text-fg-dim">三市对比</h2>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        {MARKET_DEFS.map((def) => (
          <CompareCard
            key={def.market}
            label={def.label}
            source={def.source}
            data={byMarket.get(def.market)}
          />
        ))}
      </div>
    </section>
  );
}
