/**
 * 市场宽度面板（/markets/cn，服务端组件）
 * 数据：backend /api/breadth（乐咕 A 股涨跌家数快照，末元素=当日）
 * 左：全市场涨跌平 Donut（复用 AdvanceDeclineChart）
 * 右：涨跌停与情绪指标（涨停/真实涨停/跌停/真实跌停/停牌/活跃度）
 * 下：近 60 日涨跌家数面积图（MarketBreadthChart）
 */
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { fetchMarketBreadth } from "@/lib/openbb";
import { AdvanceDeclineChart } from "@/components/advance-decline-chart";
import { MarketBreadthChart } from "@/components/market-breadth-chart";
import { EmptyState } from "@/components/empty-state";

/** 单个情绪指标（照 index-card 的 label/value 排布） */
function SentimentMetric({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "up" | "down";
}) {
  const colorClass =
    tone === "up" ? "text-up" : tone === "down" ? "text-down" : "text-fg-dim";
  return (
    <div className="flex flex-col gap-1">
      <span className="text-[10px] tracking-wider text-muted">{label}</span>
      <span className={`tab-nums text-xl font-semibold ${colorClass}`}>
        {value}
      </span>
    </div>
  );
}

function fmtCount(v: number | null): string {
  return v != null ? v.toLocaleString("zh-CN") : "—";
}

export async function MarketBreadthPanel() {
  // 一次拉取：末元素=当日快照，全序列=近 60 日趋势
  const series = await fetchMarketBreadth(60);
  const latest = series.length > 0 ? series[series.length - 1] : null;

  if (!latest) {
    return (
      <Card
        size="sm"
        className="@container/card bg-linear-to-t from-primary/5 to-card shadow-xs dark:bg-card"
      >
        <CardHeader>
          <CardTitle className="text-base font-medium text-fg-dim">
            市场宽度
          </CardTitle>
        </CardHeader>
        <CardContent>
          <EmptyState title="暂无市场宽度数据" />
        </CardContent>
      </Card>
    );
  }

  const donut = {
    up: latest.up_count ?? 0,
    down: latest.down_count ?? 0,
    flat: latest.flat_count ?? 0,
  };
  const trend = series.map((b) => ({
    date: b.date,
    up: b.up_count,
    down: b.down_count,
  }));

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {/* 全市场涨跌平（真实全市场口径，非 30 只样本） */}
        <Card
          size="sm"
          className="@container/card bg-linear-to-t from-primary/5 to-card shadow-xs dark:bg-card"
        >
          <CardHeader>
            <CardTitle className="text-base font-medium text-fg-dim">
              全市场涨跌平
            </CardTitle>
            <CardDescription>{latest.date} · 乐咕乐股</CardDescription>
          </CardHeader>
          <CardContent className="px-2 pt-2 sm:px-4 sm:pt-4">
            <AdvanceDeclineChart data={donut} />
          </CardContent>
        </Card>

        {/* 涨跌停与情绪指标 */}
        <Card
          size="sm"
          className="@container/card bg-linear-to-t from-primary/5 to-card shadow-xs dark:bg-card"
        >
          <CardHeader>
            <CardTitle className="text-base font-medium text-fg-dim">
              涨跌停与情绪
            </CardTitle>
            <CardDescription>{latest.date} · 乐咕乐股</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 gap-x-6 gap-y-5 sm:grid-cols-3">
              <SentimentMetric
                label="涨停"
                value={fmtCount(latest.limit_up_count)}
                tone="up"
              />
              <SentimentMetric
                label="真实涨停"
                value={fmtCount(latest.real_limit_up_count)}
                tone="up"
              />
              <SentimentMetric
                label="活跃度"
                value={
                  latest.activity_rate != null
                    ? `${latest.activity_rate.toFixed(2)}%`
                    : "—"
                }
              />
              <SentimentMetric
                label="跌停"
                value={fmtCount(latest.limit_down_count)}
                tone="down"
              />
              <SentimentMetric
                label="真实跌停"
                value={fmtCount(latest.real_limit_down_count)}
                tone="down"
              />
              <SentimentMetric
                label="停牌"
                value={fmtCount(latest.suspended_count)}
              />
            </div>
          </CardContent>
        </Card>
      </div>

      {/* 近 60 日涨跌家数 */}
      <Card
        size="sm"
        className="@container/card bg-linear-to-t from-primary/5 to-card shadow-xs dark:bg-card"
      >
        <CardHeader>
          <CardTitle className="text-base font-medium text-fg-dim">
            近 60 日涨跌家数
          </CardTitle>
        </CardHeader>
        <CardContent className="px-2 pt-2 sm:px-4 sm:pt-4">
          <MarketBreadthChart data={trend} />
        </CardContent>
      </Card>
    </div>
  );
}
