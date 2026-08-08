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
import { HkMarketTabs, type HkQuoteFreshness } from "./hk-market-tabs";
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

const WEEKDAY_STALE_MS = 36 * 60 * 60 * 1000;
const WEEKEND_STALE_MS = 72 * 60 * 60 * 1000;

function hongKongDateParts(value: Date): {
  date: string;
  time: string;
  weekday: string;
} {
  const parts = new Intl.DateTimeFormat("en-CA", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    weekday: "short",
    hour12: false,
    timeZone: "Asia/Hong_Kong",
  }).formatToParts(value);
  const part = (type: Intl.DateTimeFormatPartTypes) =>
    parts.find((item) => item.type === type)?.value ?? "";

  return {
    date: `${part("year")}-${part("month")}-${part("day")}`,
    time: `${part("hour")}:${part("minute")}`,
    weekday: part("weekday"),
  };
}

function validQuoteDate(value: string | null | undefined): Date | null {
  if (!value) return null;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return null;
  return parsed;
}

function formatQuoteRange(
  oldest: Date | null,
  latest: Date | null,
  fallback: string
): string {
  if (!oldest || !latest) return fallback;
  const start = hongKongDateParts(oldest);
  const end = hongKongDateParts(latest);
  if (oldest.getTime() === latest.getTime()) {
    return `${start.date} ${start.time}`;
  }
  if (start.date === end.date) {
    return `${start.date} ${start.time}–${end.time}`;
  }
  return `${start.date} ${start.time}–${end.date} ${end.time}`;
}

function quoteFreshness(
  symbol: string,
  dataAsOf: string | null | undefined,
  fetchedAt: string | null | undefined,
  now: Date
): HkQuoteFreshness {
  const parsed = validQuoteDate(dataAsOf);
  const fetched = validQuoteDate(fetchedAt);
  const fetchedLabel = fetched
    ? `${hongKongDateParts(fetched).date} ${hongKongDateParts(fetched).time}`
    : null;
  if (!parsed) {
    return { symbol, isStale: true, cutoffLabel: null, fetchedLabel };
  }

  const currentLocal = hongKongDateParts(now);
  const quoteLocal = hongKongDateParts(parsed);
  const isWeekend =
    currentLocal.weekday === "Sat" || currentLocal.weekday === "Sun";
  const staleAfterMs = isWeekend ? WEEKEND_STALE_MS : WEEKDAY_STALE_MS;
  const ageMs = now.getTime() - parsed.getTime();

  return {
    symbol,
    isStale:
      ageMs < -5 * 60 * 1000 ||
      ageMs > staleAfterMs ||
      quoteLocal.date > currentLocal.date,
    cutoffLabel: `${quoteLocal.date} ${quoteLocal.time}`,
    fetchedLabel,
  };
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
  const hasData = Boolean(
    summary?.coverage_sufficient && summary.coverage_count > 0
  );
  const coverageLabel = summary
    ? `${summary.coverage_count.toLocaleString("zh-CN")} 只`
    : "至少 1,000 只";

  return (
    <MarketSummaryCard
      title="市场宽度 · 日 K"
      description={`快照 ${shortSummaryDate(summary?.date ?? null)} · 实际覆盖 ${coverageLabel}`}
      className="h-full"
      action={
        <Badge variant="secondary" className="text-[10px]">
          日 K
        </Badge>
      }
    >
      {hasData && summary ? (
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
          description="未找到覆盖至少 1,000 只标的的有效日 K 快照"
          className="min-h-36 justify-center"
        />
      )}
    </MarketSummaryCard>
  );
}

function HkSnapshotCard({
  summary,
  usdcnh,
  quoteRange,
  quoteFetchRange,
  quoteCoverage,
}: {
  summary: MarketSummary | undefined;
  usdcnh: CrossAssetItem | undefined;
  quoteRange: string;
  quoteFetchRange: string;
  quoteCoverage: number;
}) {
  const upRatio = summary?.up_ratio ?? null;

  return (
    <MarketSummaryCard
      title="港股快照"
      description={`行情截止 ${quoteRange} · 覆盖 ${quoteCoverage}/${HK_SYMBOLS.length} · 抓取 ${quoteFetchRange} · 宽度 ${shortSummaryDate(summary?.date ?? null)}`}
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
  const now = new Date();
  const pricedQuotes = quotes.filter((quote) => quote.last_price != null);
  const quoteDates = pricedQuotes
    .map((quote) => validQuoteDate(quote.data_as_of))
    .filter((value): value is Date => value !== null)
    .sort((a, b) => a.getTime() - b.getTime());
  const fetchedDates = pricedQuotes
    .map((quote) => validQuoteDate(quote.fetched_at))
    .filter((value): value is Date => value !== null)
    .sort((a, b) => a.getTime() - b.getTime());
  const oldestQuote = quoteDates[0] ?? null;
  const latestQuote = quoteDates.at(-1) ?? null;
  const oldestFetch = fetchedDates[0] ?? null;
  const latestFetch = fetchedDates.at(-1) ?? null;
  const quoteRange = formatQuoteRange(
    oldestQuote,
    latestQuote,
    "行情时间未知"
  );
  const quoteFetchRange = formatQuoteRange(
    oldestFetch,
    latestFetch,
    "抓取时间未知"
  );
  const quoteCoverage = pricedQuotes.length;
  const quoteFreshnessRows = quotes.map((quote) =>
    quoteFreshness(
      quote.symbol,
      quote.data_as_of,
      quote.fetched_at,
      now
    )
  );
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
      quoteRange={quoteRange}
      quoteFetchRange={quoteFetchRange}
      quoteCoverage={quoteCoverage}
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
        quoteRange={quoteRange}
        quoteFetchRange={quoteFetchRange}
        quoteCoverage={quoteCoverage}
        quoteFreshness={quoteFreshnessRows}
        earnings={earnings}
        news={validNews}
        snapshot={snapshot}
        coverage={coverage}
      />

    </section>
  );
}
