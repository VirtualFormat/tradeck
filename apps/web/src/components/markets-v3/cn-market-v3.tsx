import type { ReactNode } from "react";

import { BoardTerrain, type BoardItem } from "@/components/board-terrain";
import { EmptyState } from "@/components/empty-state";
import { FundFlowBoard } from "@/components/fund-flow-board";
import { CnLiquidityStrip } from "@/components/markets-v3/cn-liquidity-strip";
import { CnMarketTabs } from "@/components/markets-v3/cn-market-tabs";
import { MoversPanel } from "@/components/dashboard/movers-panel";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardAction,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  fetchAnnouncements,
  fetchBoardHeat,
  fetchMarketBreadth,
  fetchMarketSummary,
  getAggregatedNews,
  type Announcement,
  type MarketBreadth,
  type MarketSummary,
  type NewsArticle,
} from "@/lib/openbb";
import { cn } from "@/lib/utils";

const CN_NEWS_SYMBOLS = [
  "600519.SH",
  "300750.SZ",
  "002594.SZ",
  "601318.SH",
];

function shortDate(value?: string | null) {
  const match = value?.match(/^\d{4}-(\d{2})-(\d{2})/);
  return match ? `${match[1]}-${match[2]}` : null;
}

function formatCount(value?: number | null) {
  return value == null ? "—" : value.toLocaleString("zh-CN");
}

function changeClass(value: number | null) {
  if (value == null || value === 0) return "text-muted-foreground";
  return value > 0 ? "text-up" : "text-down";
}

function formatChange(value: number | null) {
  if (value == null) return "—";
  return `${value > 0 ? "+" : ""}${value.toFixed(2)}%`;
}

function findBreadth(
  rows: MarketBreadth[],
  targetDate?: string | null
): MarketBreadth | null {
  const cnRows = rows.filter((row) => row.market === "CN");
  if (targetDate) {
    return cnRows.find((row) => row.date === targetDate) ?? null;
  }
  return cnRows.at(-1) ?? null;
}

function MarketBreadthCard({
  summary,
  breadth,
}: {
  summary?: MarketSummary | null;
  breadth?: MarketBreadth | null;
}) {
  const totalDirectional = (summary?.up ?? 0) + (summary?.down ?? 0);
  const upRatio =
    summary?.up_ratio ??
    (totalDirectional > 0 ? (summary?.up ?? 0) / totalDirectional : null);

  return (
    <Card size="sm" className="min-h-[150px] gap-2 py-3 shadow-none xl:min-h-[210px]">
      <CardHeader className="px-4">
        <CardTitle className="text-sm font-semibold text-fg-dim">
          市场宽度
        </CardTitle>
        <CardAction className="flex items-center gap-1.5 text-[10px] text-muted-foreground">
          <span>乐咕乐股</span>
          {summary?.date && <span>{shortDate(summary.date)}</span>}
        </CardAction>
      </CardHeader>
      <CardContent className="flex flex-1 flex-col justify-center gap-3 px-4">
        {summary && summary.total > 0 ? (
          <>
            <p className="text-lg font-semibold tabular-nums text-foreground sm:text-xl">
              涨 {formatCount(summary.up)}
              <span className="px-1.5 text-muted-foreground">·</span>
              平 {formatCount(summary.flat)}
              <span className="px-1.5 text-muted-foreground">·</span>
              跌 {formatCount(summary.down)}
            </p>
            <div className="h-2 overflow-hidden rounded-full bg-muted">
              <div
                className="h-full rounded-full bg-up"
                style={{
                  width: `${Math.max(0, Math.min(100, (upRatio ?? 0) * 100))}%`,
                }}
              />
            </div>
            <p className="text-xs text-muted-foreground">
              上涨占比{" "}
              <span className="tabular-nums text-foreground">
                {upRatio == null ? "—" : `${(upRatio * 100).toFixed(0)}%`}
              </span>
              <span className="px-2">·</span>
              涨停 {formatCount(breadth?.limit_up_count ?? summary.limit_up)}
              <span className="px-2">·</span>
              跌停 {formatCount(breadth?.limit_down_count ?? summary.limit_down)}
            </p>
          </>
        ) : (
          <EmptyState
            compact
            title="等待市场宽度数据"
            className="min-h-24 justify-center"
          />
        )}
      </CardContent>
    </Card>
  );
}

function deriveFocus(summary: MarketSummary | null, boards: BoardItem[]) {
  const gainers = boards
    .filter((item) => item.change_percent != null && item.change_percent > 0)
    .sort(
      (a, b) => (b.change_percent ?? -Infinity) - (a.change_percent ?? -Infinity)
    )
    .slice(0, 3);
  const losers = boards
    .filter((item) => item.change_percent != null && item.change_percent < 0)
    .sort(
      (a, b) => (a.change_percent ?? Infinity) - (b.change_percent ?? Infinity)
    )
    .slice(0, 3);
  const ratio = summary?.up_ratio;
  const tone =
    ratio == null
      ? null
      : ratio >= 0.6
        ? "上涨家数占优"
        : ratio <= 0.4
          ? "下跌家数占优"
          : "多空分化";

  return { gainers, losers, tone };
}

function FocusCard({
  summary,
  boards,
}: {
  summary: MarketSummary | null;
  boards: BoardItem[];
}) {
  const { gainers, losers, tone } = deriveFocus(summary, boards);
  const boardDate = boards[0]?.snapshot_date;

  return (
    <Card size="sm" className="min-h-[150px] gap-2 py-3 shadow-none xl:min-h-[210px]">
      <CardHeader className="px-4">
        <CardTitle className="text-sm font-semibold text-fg-dim">
          今日焦点
        </CardTitle>
        <CardAction className="text-[10px] text-muted-foreground">
          宽度 {shortDate(summary?.date) ?? "—"} / 行业{" "}
          {shortDate(boardDate) ?? "—"}
        </CardAction>
      </CardHeader>
      <CardContent className="space-y-2 px-4 text-xs">
        {tone || gainers.length > 0 || losers.length > 0 ? (
          <>
            {tone && (
              <p className="font-medium text-warn">
                {tone}
                {summary?.up_ratio != null
                  ? ` · 上涨占比 ${(summary.up_ratio * 100).toFixed(0)}%`
                  : ""}
              </p>
            )}
            {losers.length > 0 && (
              <p className="line-clamp-2 leading-5 text-muted-foreground">
                领跌：
                {losers
                  .map(
                    (item) =>
                      `${item.name} ${formatChange(item.change_percent)}`
                  )
                  .join(" · ")}
              </p>
            )}
            {gainers.length > 0 && (
              <p className="line-clamp-2 leading-5 text-muted-foreground">
                逆势：
                {gainers
                  .map(
                    (item) =>
                      `${item.name} ${formatChange(item.change_percent)}`
                  )
                  .join(" · ")}
              </p>
            )}
          </>
        ) : (
          <EmptyState
            compact
            title="等待盘面焦点"
            className="min-h-24 justify-center"
          />
        )}
      </CardContent>
    </Card>
  );
}

function IndustryMobileList({
  boards,
  date,
}: {
  boards: BoardItem[];
  date?: string | null;
}) {
  const rows = [...boards]
    .filter((item) => item.change_percent != null)
    .sort(
      (a, b) =>
        Math.abs(b.change_percent ?? 0) - Math.abs(a.change_percent ?? 0)
    )
    .slice(0, 8);
  const source = boards[0]?.source === "ths" ? "同花顺行业" : "东财行业";

  return (
    <Card size="sm" className="gap-2 py-3 shadow-none">
      <CardHeader className="px-3.5">
        <CardTitle className="text-sm font-semibold text-fg-dim">
          行业轮动 · Top 8
        </CardTitle>
        <CardAction className="text-[10px] text-muted-foreground">
          {source}
          {date ? ` · ${shortDate(date)}` : ""}
        </CardAction>
      </CardHeader>
      <CardContent className="px-3.5">
        {rows.length > 0 ? (
          <div className="grid grid-cols-1 gap-x-5 sm:grid-cols-2">
            {rows.map((item) => (
              <div
                key={`${item.code ?? ""}-${item.name}`}
                className="flex min-h-8 items-center justify-between gap-3 border-b border-border/60 py-1 last:border-b-0 sm:[&:nth-last-child(-n+2)]:border-b-0"
              >
                <span className="min-w-0 truncate text-xs text-fg-dim">
                  {item.name}
                </span>
                <span
                  className={cn(
                    "shrink-0 text-xs font-medium tabular-nums",
                    changeClass(item.change_percent)
                  )}
                >
                  {formatChange(item.change_percent)}
                </span>
              </div>
            ))}
          </div>
        ) : (
          <EmptyState
            compact
            title="等待行业数据"
            className="min-h-40 justify-center"
          />
        )}
        {boards.length > rows.length && (
          <p className="pt-2 text-[10px] text-muted-foreground">
            当前共覆盖 {boards.length} 个行业；完整板块在桌面热力图中查看
          </p>
        )}
      </CardContent>
    </Card>
  );
}

function CompanyEventsCard({
  announcements,
}: {
  announcements: Announcement[];
}) {
  return (
    <Card size="sm" className="gap-1.5 py-3 shadow-none">
      <CardHeader className="px-3.5">
        <CardTitle className="text-xs font-semibold text-fg-dim">
          公司事件
        </CardTitle>
        <CardAction className="text-[10px] text-muted-foreground">
          A股公告 · 东财
        </CardAction>
      </CardHeader>
      <CardContent className="px-3.5">
        {announcements.length > 0 ? (
          <div className="flex flex-col">
            {announcements.slice(0, 5).map((item) => {
              const content = (
                <>
                  <Badge
                    variant="secondary"
                    className="mt-0.5 h-4 max-w-20 shrink-0 rounded-sm px-1.5 py-0 text-[10px]"
                  >
                    <span className="truncate">{item.symbol}</span>
                  </Badge>
                  <span className="line-clamp-2 min-w-0 flex-1 text-xs leading-4 text-fg-dim">
                    {item.title}
                  </span>
                  <span className="shrink-0 text-[10px] tabular-nums text-muted-foreground">
                    {shortDate(item.publish_date)}
                  </span>
                </>
              );

              return item.url ? (
                <a
                  key={`${item.symbol}-${item.publish_date}-${item.title}`}
                  href={item.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex min-h-10 items-start gap-2 border-b border-border/60 py-1.5 transition-colors last:border-b-0 hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
                >
                  {content}
                </a>
              ) : (
                <div
                  key={`${item.symbol}-${item.publish_date}-${item.title}`}
                  className="flex min-h-10 items-start gap-2 border-b border-border/60 py-1.5 last:border-b-0"
                >
                  {content}
                </div>
              );
            })}
          </div>
        ) : (
          <EmptyState
            compact
            title="暂无近期公司公告"
            className="min-h-32 justify-center"
          />
        )}
      </CardContent>
    </Card>
  );
}

function CnNewsCard({ articles }: { articles: NewsArticle[] }) {
  const seen = new Set<string>();
  const rows = articles
    .filter((item) => item.title?.trim() && item.url?.trim())
    .filter((item) => {
      if (seen.has(item.url)) return false;
      seen.add(item.url);
      return true;
    })
    .slice(0, 5);

  return (
    <Card size="sm" className="gap-1.5 py-3 shadow-none">
      <CardHeader className="px-3.5">
        <CardTitle className="text-xs font-semibold text-fg-dim">
          A股资讯
        </CardTitle>
        <CardAction className="text-[10px] text-muted-foreground">
          代表标的聚合
        </CardAction>
      </CardHeader>
      <CardContent className="px-3.5">
        {rows.length > 0 ? (
          <div className="flex flex-col">
            {rows.map((item) => (
              <a
                key={`${item.symbol}-${item.url}`}
                href={item.url}
                target="_blank"
                rel="noopener noreferrer"
                className="flex min-h-10 items-start gap-2 border-b border-border/60 py-1.5 transition-colors last:border-b-0 hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
              >
                <Badge
                  variant="secondary"
                  className="mt-0.5 h-4 max-w-20 shrink-0 rounded-sm px-1.5 py-0 text-[10px] text-up"
                >
                  <span className="truncate">{item.symbol}</span>
                </Badge>
                <span className="line-clamp-2 min-w-0 flex-1 text-xs leading-4 text-fg-dim">
                  {item.title}
                </span>
              </a>
            ))}
          </div>
        ) : (
          <EmptyState
            compact
            title="暂无 A股资讯"
            className="min-h-32 justify-center"
          />
        )}
      </CardContent>
    </Card>
  );
}

function MobileEvents({
  companyEvents,
  news,
}: {
  companyEvents: ReactNode;
  news: ReactNode;
}) {
  return (
    <div className="space-y-3">
      {companyEvents}
      {news}
    </div>
  );
}

export async function CnMarketV3({ date }: { date?: string }) {
  const [
    summaries,
    breadthRows,
    boards,
    announcements,
    news,
    moversPanel,
    fundFlowPanel,
  ] = await Promise.all([
    fetchMarketSummary(date).catch(() => [] as MarketSummary[]),
    fetchMarketBreadth(60).catch(() => [] as MarketBreadth[]),
    fetchBoardHeat("industry", date, 120, "market_cap").catch(
      () => [] as BoardItem[]
    ),
    fetchAnnouncements(undefined, 14).catch(() => [] as Announcement[]),
    getAggregatedNews(CN_NEWS_SYMBOLS, 2).catch(() => [] as NewsArticle[]),
    MoversPanel({ market: "cn", date }),
    FundFlowBoard({ date, variant: "dashboard" }),
  ]);

  const summary =
    summaries.find((item) => item.market.toUpperCase() === "CN") ?? null;
  const breadth = findBreadth(breadthRows, summary?.date ?? date);
  const boardDate = boards[0]?.snapshot_date ?? date ?? null;
  const boardSource = boards[0]?.source ?? null;
  const sizeBasis = boards[0]?.size_basis ?? null;

  const industryDesktop = (
    <BoardTerrain
      items={boards}
      variant="dashboard"
      date={boardDate ?? undefined}
      referenceDate={summary?.date ?? null}
      source={boardSource}
      sizeBasis={sizeBasis}
    />
  );
  const industryMobile = (
    <IndustryMobileList boards={boards} date={boardDate} />
  );
  const companyEvents = (
    <CompanyEventsCard announcements={announcements} />
  );
  const cnNews = <CnNewsCard articles={news} />;
  const mobileEvents = (
    <MobileEvents companyEvents={companyEvents} news={cnNews} />
  );

  return (
    <section className="space-y-3">
      <div className="grid grid-cols-1 gap-3 xl:grid-cols-[minmax(0,1fr)_20rem]">
        <MarketBreadthCard summary={summary} breadth={breadth} />
        <FocusCard summary={summary} boards={boards} />
      </div>

      <CnLiquidityStrip breadth={breadth} />

      <CnMarketTabs
        movers={moversPanel}
        industryDesktop={industryDesktop}
        industryMobile={industryMobile}
        funds={fundFlowPanel}
        events={mobileEvents}
      />
    </section>
  );
}
