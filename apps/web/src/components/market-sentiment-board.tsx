/**
 * 首页三市情绪总览：市场宽度支持日期快照，代表指数始终显示最新交易日。
 * 不展示数据层没有稳定来源的成交额、资金流或领涨板块。
 */
import {
  Card,
  CardAction,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/empty-state";
import { MarketBreadthBar } from "@/components/dashboard/market-breadth-bar";
import {
  fetchMarketSummary,
  getIndexHistorical,
  type MarketSummary,
} from "@/lib/openbb";
import { fmtDataDate, fmtPrice, fmtPct } from "@/lib/format";

const MARKET_DEFS: Array<{
  market: string;
  label: string;
  indexSymbol: string;
  indexName: string;
  sourceLabel: string;
}> = [
  {
    market: "CN",
    label: "A股",
    indexSymbol: "000001.SS",
    indexName: "上证",
    sourceLabel: "乐咕",
  },
  {
    market: "US",
    label: "美股",
    indexSymbol: "^GSPC",
    indexName: "标普",
    sourceLabel: "日K",
  },
  {
    market: "HK",
    label: "港股",
    indexSymbol: "^HSI",
    indexName: "恒指",
    sourceLabel: "日K",
  },
];

interface IndexQuote {
  price: number | null;
  changePct: number | null;
}

async function fetchIndexQuote(symbol: string): Promise<IndexQuote> {
  const end = new Date();
  const start = new Date(end.getTime() - 14 * 24 * 60 * 60 * 1000);
  const fmt = (d: Date) => d.toISOString().slice(0, 10);

  try {
    const hist = await getIndexHistorical(symbol, fmt(start), fmt(end));
    if (hist.length === 0) return { price: null, changePct: null };

    const last = hist[hist.length - 1];
    const prev = hist.length > 1 ? hist[hist.length - 2] : last;
    return {
      price: last.close,
      changePct:
        prev.close > 0 ? (last.close - prev.close) / prev.close : 0,
    };
  } catch (err) {
    console.error(`MarketSentimentBoard index ${symbol} failed:`, err);
    return { price: null, changePct: null };
  }
}

function sentiment(
  upRatio: number | null
): { label: string; className: string } | null {
  if (upRatio == null) return null;
  if (upRatio >= 0.6) return { label: "偏多", className: "text-up" };
  if (upRatio >= 0.45) {
    return { label: "中性", className: "text-muted-foreground" };
  }
  return { label: "偏空", className: "text-down" };
}

function SentimentCard({
  label,
  indexName,
  sourceLabel,
  data,
  quote,
}: {
  label: string;
  indexName: string;
  sourceLabel: string;
  data: MarketSummary | undefined;
  quote: IndexQuote;
}) {
  const dateLabel = fmtDataDate(data?.date ?? null);
  const hasData =
    data != null && (data.up > 0 || data.down > 0 || data.flat > 0);
  const upPct =
    data != null && data.total > 0
      ? Math.round((data.up / data.total) * 100)
      : null;
  const showLimit =
    data != null && data.limit_up != null && data.limit_down != null;
  const mood = sentiment(data?.up_ratio ?? null);
  const quoteClass =
    quote.changePct == null || quote.changePct === 0
      ? "text-muted-foreground"
      : quote.changePct > 0
        ? "text-up"
        : "text-down";

  return (
    <Card size="sm" className="min-h-[164px] gap-2 py-3.5">
      <CardHeader className="px-[18px]">
        <CardTitle>
          <Badge
            variant="outline"
            className="h-[18px] rounded-md px-2 text-[11px] text-fg-dim"
          >
            {label}
          </Badge>
        </CardTitle>
        {mood ? (
          <CardAction className={`text-[11px] font-medium ${mood.className}`}>
            {mood.label}
          </CardAction>
        ) : null}
      </CardHeader>

      <CardContent className="flex flex-1 flex-col gap-2 px-[18px]">
        <div className="flex min-w-0 items-baseline gap-2 whitespace-nowrap">
          <span className="truncate text-[clamp(1.05rem,1.5vw,1.375rem)] leading-7 font-semibold text-foreground tabular-nums">
            {indexName} {fmtPrice(quote.price)}
          </span>
          <span
            className={`shrink-0 text-xs font-medium tabular-nums sm:text-sm ${quoteClass}`}
          >
            {fmtPct(quote.changePct)}
          </span>
        </div>

        {hasData ? (
          <>
            <MarketBreadthBar
              up={data.up}
              flat={data.flat}
              down={data.down}
            />

            <div className="flex min-w-0 flex-wrap items-center justify-between gap-x-3 gap-y-1 text-[11px] tabular-nums">
              <span className="text-muted-foreground">
                涨 {data.up} · 平 {data.flat} · 跌 {data.down}
              </span>
              {showLimit ? (
                <span className="text-fg-dim">
                  <span className="text-up">涨停 {data.limit_up}</span>
                  {" · "}
                  <span className="text-down">跌停 {data.limit_down}</span>
                </span>
              ) : null}
            </div>

            <div className="mt-auto flex items-center justify-between gap-3 text-[11px]">
              <span className="text-muted-foreground">
                上涨占比{" "}
                <span className="text-fg-dim tabular-nums">
                  {upPct != null ? `${upPct}%` : "—"}
                </span>
              </span>
              <span className="shrink-0 font-medium text-fg-dim tabular-nums">
                {dateLabel ? `${dateLabel} · ${sourceLabel}` : sourceLabel}
              </span>
            </div>
          </>
        ) : (
          <EmptyState
            compact
            title="等待市场宽度数据"
            className="min-h-16 w-full"
          />
        )}
      </CardContent>
    </Card>
  );
}

export async function MarketSentimentBoard({ date }: { date?: string }) {
  let summary: MarketSummary[] = [];
  try {
    summary = await fetchMarketSummary(date);
  } catch (err) {
    console.error("MarketSentimentBoard fetchMarketSummary failed:", err);
  }
  const byMarket = new Map(summary.map((item) => [item.market, item]));
  const quotes = await Promise.all(
    MARKET_DEFS.map((def) => fetchIndexQuote(def.indexSymbol))
  );
  const anyData = summary.some(
    (item) => item.up > 0 || item.down > 0 || item.flat > 0
  );
  const latestSummaryDate = summary
    .map((item) => item.date)
    .filter((value): value is string => Boolean(value))
    .sort()
    .pop();
  const summaryDateLabel = fmtDataDate(latestSummaryDate);

  return (
    <section>
      <div className="mb-2.5 flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-medium text-fg-dim">
          市场情绪总览
          {summaryDateLabel
            ? ` · ${date ? "快照" : "截至"} ${summaryDateLabel}`
            : ""}
        </h2>
        <span className="text-[11px] text-muted-foreground">
          代表指数 · 最新
        </span>
      </div>

      {anyData ? (
        <div className="grid grid-cols-1 items-stretch gap-4 md:grid-cols-2 xl:grid-cols-3">
          {MARKET_DEFS.map((def, index) => (
            <SentimentCard
              key={def.market}
              label={def.label}
              indexName={def.indexName}
              sourceLabel={def.sourceLabel}
              data={byMarket.get(def.market)}
              quote={quotes[index]}
            />
          ))}
        </div>
      ) : (
        <Card size="sm" className="flex h-40 items-center justify-center">
          <EmptyState compact title="等待市场情绪数据" />
        </Card>
      )}
    </section>
  );
}
