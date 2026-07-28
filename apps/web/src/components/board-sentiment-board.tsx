/**
 * 板块舆情榜（服务端组件）
 * - 数据：backend /api/boards/sentiment
 * - 单榜 Top 10，按舆情热度倒序（百分制），含 24h 新闻量与情绪均值
 */
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { BoardTypeTabs } from "@/components/board-type-tabs";
import { EmptyState } from "@/components/empty-state";
import { fmtDataDate } from "@/lib/format";

export interface BoardSentimentItem {
  name: string;
  news_count: number;
  sentiment_avg: number | null;
  hot_score: number | null;
  /** 聚合更新时间（board_sentiment.updated_at，其日期即快照日） */
  updated_at?: string | null;
}

async function fetchSentiment(
  type: string,
  date?: string
): Promise<BoardSentimentItem[]> {
  const BACKEND_API_URL =
    process.env.BACKEND_API_URL ?? "http://localhost:8080";
  try {
    const dateQuery = date ? `&date=${date}` : "";
    const res = await fetch(
      `${BACKEND_API_URL}/api/boards/sentiment?type=${type}&limit=10&order=desc${dateQuery}`,
      { headers: { Accept: "application/json" } }
    );
    if (!res.ok) return [];
    const data = await res.json();
    return Array.isArray(data) ? data : [];
  } catch {
    return [];
  }
}

function SentimentBadge({ value }: { value: number | null }) {
  if (value == null) return <span className="text-[10px] text-muted-foreground">—</span>;
  const cls = value >= 0 ? "text-up" : "text-down";
  return (
    <span className={`tab-nums text-[10px] ${cls}`}>
      {value > 0 ? "+" : ""}
      {value.toFixed(2)}
    </span>
  );
}

export async function BoardSentimentBoard({
  type,
  date,
}: {
  type: string;
  date?: string;
}) {
  const items = await fetchSentiment(type, date);
  // 快照日期：用聚合 updated_at 的日期（日频快照）
  const dateLabel = fmtDataDate(items[0]?.updated_at);

  return (
    <Card
      size="sm"
      className="@container/card bg-linear-to-t from-primary/5 to-card shadow-xs dark:bg-card"
    >
      <CardHeader>
        <CardTitle className="text-base font-medium text-fg-dim">
          板块舆情热度榜 Top 10
        </CardTitle>
        <CardAction>
          <BoardTypeTabs />
        </CardAction>
        <CardDescription className="truncate text-[10px]">
          热度倒序 · 新闻量 · 情绪均值
          {dateLabel && (
            <span className="ml-1 text-muted-foreground">· {dateLabel}</span>
          )}
        </CardDescription>
      </CardHeader>
      <CardContent>
        {items.length > 0 ? (
          items.map((item, i) => (
            <div
              key={item.name}
              className="flex items-center justify-between border-b border-border/40 py-1.5 last:border-0"
            >
              <div className="flex min-w-0 flex-1 items-center gap-2">
                <span className="w-4 shrink-0 text-[10px] text-muted-foreground">
                  {i + 1}
                </span>
                <span className="truncate text-xs font-medium">{item.name}</span>
                <span className="shrink-0 text-[10px] text-muted-foreground">
                  {item.news_count} 条
                </span>
              </div>
              <div className="flex shrink-0 items-center gap-3">
                <SentimentBadge value={item.sentiment_avg} />
                <span className="tab-nums w-12 text-right text-xs font-semibold text-fg">
                  {item.hot_score != null
                    ? (item.hot_score * 100).toFixed(1)
                    : "—"}
                </span>
              </div>
            </div>
          ))
        ) : (
          <EmptyState compact title="无数据" />
        )}
      </CardContent>
    </Card>
  );
}
