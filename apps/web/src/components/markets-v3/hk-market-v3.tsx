import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/empty-state";
import { fmtDataDate, fmtPrice } from "@/lib/format";
import {
  fetchCrossAssets,
  fetchEarningsCalendar,
  fetchMarketSummary,
  getAggregatedNews,
  getEquityQuotes,
  type CrossAssetItem,
  type MarketSummary,
} from "@/lib/openbb";
import { cn } from "@/lib/utils";

import { HkCoverageCard } from "./hk-coverage-card";
import {
  HkMarketTabs,
} from "./hk-market-tabs";
import { MarketSummaryCard } from "./market-summary-card";

const HK_SYMBOLS = [
  "00700.HK",
  "09988.HK",
  "00005.HK",
  "01299.HK",
  "00883.HK",
  "00939.HK",
  "00388.HK",
  "02318.HK",
  "00941.HK",
  "01810.HK",
  "03690.HK",
  "09618.HK",
];

const HK_NEWS_SYMBOLS = [
  "00700.HK",
  "09988.HK",
  "01810.HK",
  "03690.HK",
];

function ratioLabel(value: number | null): string {
  if (value == null) return "等待数据";
  if (value >= 0.55) return "偏强";
  if (value <= 0.45) return "偏弱";
  return "均衡";
}

function ratioClass(value: number | null): string {
  if (value == null) return "text-muted-foreground";
  if (value >= 0.55) return "text-up";
  if (value <= 0.45) return "text-down";
  return "text-warn";
}

function shortSummaryDate(value: string | null): string {
  return fmtDataDate(value) ?? "等待数据";
}

function crossAssetChangeClass(value: number | null): string {
  if (value == null || value === 0) return "text-muted-foreground";
  return value > 0 ? "text-up" : "text-down";
}

function formatShanghaiTime(value: string | null | undefined): string | null {
  if (!value) return null;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return null;
  return new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: "Asia/Shanghai",
  }).format(parsed);
}

function SnapshotTile({
  label,
  value,
  note,
  noteClass,
}: {
  label: string;
  value: string;
  note: string;
  noteClass?: string;
}) {
  return (
    <div className="min-w-0 rounded-lg bg-secondary px-3 py-2.5">
      <div className="truncate text-[10px] text-muted-foreground">{label}</div>
      <div className="mt-1 truncate text-base font-semibold text-foreground tabular-nums">
        {value}
      </div>
      <div
        className={cn(
          "mt-0.5 truncate text-[10px] font-medium tabular-nums",
          noteClass ?? "text-muted-foreground"
        )}
      >
        {note}
      </div>
    </div>
  );
}

function HkBreadthCard({ summary }: { summary: MarketSummary | undefined }) {
  const upRatio = summary?.up_ratio ?? null;

  return (
    <MarketSummaryCard
      title="市场宽度 · 日 K 全市场"
      description={`快照 ${shortSummaryDate(summary?.date ?? null)} · 平盘计入总数但不计上涨占比`}
      className="h-full"
      action={
        <Badge variant="secondary" className="text-[10px]">
          日 K
        </Badge>
      }
    >
      {summary ? (
        <div className="space-y-4">
          <div className="grid grid-cols-3 gap-2">
            <SnapshotTile
              label="上涨"
              value={summary.up.toLocaleString("zh-CN")}
              note="家"
              noteClass="text-up"
            />
            <SnapshotTile
              label="平盘"
              value={summary.flat.toLocaleString("zh-CN")}
              note="家"
            />
            <SnapshotTile
              label="下跌"
              value={summary.down.toLocaleString("zh-CN")}
              note="家"
              noteClass="text-down"
            />
          </div>
          <div>
            <div className="mb-2 flex items-center justify-between gap-3 text-xs">
              <span className="text-muted-foreground">上涨占比</span>
              <span
                className={cn(
                  "font-medium tabular-nums",
                  ratioClass(upRatio)
                )}
              >
                {upRatio == null ? "—" : `${(upRatio * 100).toFixed(0)}%`}
                {upRatio != null ? ` · ${ratioLabel(upRatio)}` : ""}
              </span>
            </div>
            <div className="flex h-2 overflow-hidden rounded-full bg-secondary">
              <div
                className="bg-up"
                style={{
                  width: `${Math.max(
                    0,
                    Math.min(100, (upRatio ?? 0) * 100)
                  )}%`,
                }}
              />
              <div className="min-w-1 flex-1 bg-down" />
            </div>
          </div>
        </div>
      ) : (
        <EmptyState
          compact
          title="暂无港股市场宽度"
          description="日 K 全市场计算完成后自动更新"
          className="min-h-36 justify-center"
        />
      )}
    </MarketSummaryCard>
  );
}

function HkSnapshotCard({
  summary,
  usdcnh,
  quoteTime,
}: {
  summary: MarketSummary | undefined;
  usdcnh: CrossAssetItem | undefined;
  quoteTime: string | null;
}) {
  const upRatio = summary?.up_ratio ?? null;

  return (
    <MarketSummaryCard
      title="港股快照"
      description={`报价 ${quoteTime ?? "等待更新"} · 宽度 ${shortSummaryDate(summary?.date ?? null)}`}
      contentClassName="grid grid-cols-2 gap-2 sm:grid-cols-4"
    >
      <SnapshotTile
        label="上涨占比"
        value={upRatio == null ? "—" : `${(upRatio * 100).toFixed(0)}%`}
        note={ratioLabel(upRatio)}
        noteClass={ratioClass(upRatio)}
      />
      <SnapshotTile
        label="离岸人民币"
        value={fmtPrice(usdcnh?.close)}
        note={
          usdcnh?.chg_1d == null
            ? "暂无变化率"
            : `${usdcnh.chg_1d > 0 ? "+" : ""}${usdcnh.chg_1d.toFixed(2)}%`
        }
        noteClass={crossAssetChangeClass(usdcnh?.chg_1d ?? null)}
      />
      <SnapshotTile
        label="港币 / 美元"
        value="—"
        note="暂无可靠覆盖"
        noteClass="text-warn"
      />
      <SnapshotTile
        label="代表标的"
        value="12 只"
        note="非全市场"
        noteClass="text-warn"
      />
    </MarketSummaryCard>
  );
}

function HkDataGaps() {
  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
      <SnapshotTile
        label="主板成交额"
        value="—"
        note="等待全市场源"
        noteClass="text-warn"
      />
      <SnapshotTile
        label="南向净流入"
        value="—"
        note="等待港股通源"
        noteClass="text-warn"
      />
      <SnapshotTile
        label="行业热力"
        value="—"
        note="等待行业分类源"
        noteClass="text-warn"
      />
      <SnapshotTile
        label="新闻覆盖"
        value="有限"
        note="代表标的采集"
        noteClass="text-muted-foreground"
      />
    </div>
  );
}

/**
 * 港股市场 V3 独立业务区。
 *
 * 页面外壳、Toolbar 和指数带由接入方组合；本组件只负责真实港股业务模块。
 */
export async function HkMarketV3({ date }: { date?: string }) {
  const [summaries, quotes, crossAssets, earnings, news] = await Promise.all([
    fetchMarketSummary(date).catch(() => []),
    getEquityQuotes(HK_SYMBOLS).catch(() => []),
    fetchCrossAssets().catch(() => []),
    fetchEarningsCalendar(30).catch(() => []),
    getAggregatedNews(HK_NEWS_SYMBOLS, 2).catch(() => []),
  ]);

  const summary = summaries.find((item) => item.market === "HK");
  const usdcnh = crossAssets.find((item) => item.symbol === "USDCNH");
  const quoteTime =
    formatShanghaiTime(
      quotes.find((quote) => quote.updated_at)?.updated_at
    ) ?? null;
  const validNews = news
    .filter((article) => article.title?.trim() && article.url?.trim())
    .filter(
      (article, index, rows) =>
        rows.findIndex((row) => row.url === article.url) === index
    );

  const snapshot = (
    <HkSnapshotCard
      summary={summary}
      usdcnh={usdcnh}
      quoteTime={quoteTime}
    />
  );
  const coverage = <HkCoverageCard />;

  return (
    <section aria-label="港股市场 V3" className="flex min-w-0 flex-col gap-4 md:gap-5">
      <div className="xl:hidden">
        <HkCoverageCard variant="notice" />
      </div>

      <div className="grid min-w-0 gap-4 xl:grid-cols-[minmax(0,1fr)_24rem]">
        <HkBreadthCard summary={summary} />
        <div className="hidden xl:block">
          <HkCoverageCard variant="summary" />
        </div>
      </div>

      <div className="hidden xl:block">
        <HkDataGaps />
      </div>

      <HkMarketTabs
        quotes={quotes}
        earnings={earnings}
        news={validNews}
        snapshot={snapshot}
        coverage={coverage}
      />

    </section>
  );
}
