/**
 * 市场情绪总览（首页 Band1，服务端组件）
 * 一行三卡（CN / US / HK），吸收并替代 market-compare-cards：
 * - 标题行：市场名 Badge + 情绪标签（由 up_ratio 推导：≥0.6 偏多 / 0.45–0.6 中性 / <0.45 偏空）
 * - 主指数行：代表指数名 + 最新价 + 涨跌%（复用 market-overview 的指数历史取数方式；取不到只显市场名）
 * - 涨跌宽度：复用 AdvanceDeclineChart 半环
 * - 涨跌家数行：涨 / 平 / 跌
 * - CN 额外：涨停 / 跌停（limit 非 null 才显）
 * - 底部（mt-auto 吸底）：上涨占比 + Progress
 *
 * 数据全部来自 openbb 真实 fetcher（fetchMarketSummary + getIndexHistorical）。
 * 成交额 / 资金流 / 领涨板块 等增量指标：openbb 无对应 fetcher → 一律隐藏（不写死 Figma 示例数字）。
 * 支持 ?date= 快照回看：透传 date 给 fetchMarketSummary（指数取最新交易日，非快照）。
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
import {
  fetchMarketSummary,
  getIndexHistorical,
  type MarketSummary,
} from "@/lib/openbb";
import { fmtDataDate, fmtPrice, fmtPct } from "@/lib/format";

// 各市场代表指数（headline，与 market-overview 的 symbol 定义一致）
const MARKET_DEFS: Array<{
  market: string;
  label: string;
  indexSymbol: string;
  indexName: string;
}> = [
  {
    market: "CN",
    label: "A股",
    indexSymbol: "000001.SS",
    indexName: "上证",
  },
  {
    market: "US",
    label: "美股",
    indexSymbol: "^GSPC",
    indexName: "标普",
  },
  {
    market: "HK",
    label: "港股",
    indexSymbol: "^HSI",
    indexName: "恒指",
  },
];

interface IndexQuote {
  price: number | null;
  changePct: number | null;
}

// 拉近 14 日指数历史，取最新 2 条算收盘价与涨跌幅（复用 market-overview 口径）
async function fetchIndexQuote(symbol: string): Promise<IndexQuote> {
  const end = new Date();
  const start = new Date(end.getTime() - 14 * 24 * 60 * 60 * 1000);
  const fmt = (d: Date) => d.toISOString().slice(0, 10);
  try {
    const hist = await getIndexHistorical(symbol, fmt(start), fmt(end));
    if (hist.length === 0) return { price: null, changePct: null };
    const last = hist[hist.length - 1];
    const prev = hist.length > 1 ? hist[hist.length - 2] : last;
    const changePct =
      prev.close > 0 ? (last.close - prev.close) / prev.close : 0;
    return { price: last.close, changePct };
  } catch (err) {
    console.error(`MarketSentimentBoard index ${symbol} failed:`, err);
    return { price: null, changePct: null };
  }
}

// 情绪标签：由 up_ratio 推导
function sentiment(
  upRatio: number | null
): { label: string; className: string } | null {
  if (upRatio == null) return null;
  if (upRatio >= 0.6) return { label: "偏多", className: "text-up" };
  if (upRatio >= 0.45)
    return { label: "中性", className: "text-muted-foreground" };
  return { label: "偏空", className: "text-down" };
}

function SentimentCard({
  label,
  indexName,
  data,
  quote,
}: {
  label: string;
  indexName: string;
  data: MarketSummary | undefined;
  quote: IndexQuote;
}) {
  const dateLabel = fmtDataDate(data?.date ?? null);
  const hasData =
    data != null && (data.up > 0 || data.down > 0 || data.flat > 0);
  const upPct = data?.up_ratio != null ? Math.round(data.up_ratio * 100) : null;
  const showLimit =
    data != null && data.limit_up != null && data.limit_down != null;
  const mood = sentiment(data?.up_ratio ?? null);

  const hasQuote = quote.price != null;
  const quoteUp = (quote.changePct ?? 0) >= 0;

  return (
    <Card
      size="sm"
      className="@container/card flex flex-col bg-linear-to-t from-primary/5 to-card shadow-xs dark:bg-card"
    >
      <CardHeader>
        <CardTitle className="text-base font-medium text-fg-dim">
          <Badge variant="outline">{label}</Badge>
        </CardTitle>
        {mood ? (
          <CardAction
            className={`text-xs font-medium ${mood.className}`}
          >
            {mood.label}
          </CardAction>
        ) : null}
      </CardHeader>

      <CardContent className="flex flex-1 flex-col gap-3">
        {/* 主指数行：名称 + 价格 + 涨跌%（取不到指数则只显市场名 headline 由 Badge 承担） */}
        {hasQuote ? (
          <div className="flex items-baseline gap-2">
            <span className="text-sm text-muted-foreground">{indexName}</span>
            <span className="text-xl font-semibold text-foreground tabular-nums">
              {fmtPrice(quote.price)}
            </span>
            <span
              className={`text-sm font-medium tabular-nums ${
                quoteUp ? "text-up" : "text-down"
              }`}
            >
              {fmtPct(quote.changePct)}
            </span>
          </div>
        ) : null}

        {hasData ? (
          <>
            {/* 涨跌宽度半环 */}
            <AdvanceDeclineChart
              data={{ up: data.up, down: data.down, flat: data.flat }}
            />

            {/* 涨跌停行：仅 CN（limit 非 null 才显） */}
            {showLimit ? (
              <div className="flex items-center justify-center gap-4 text-xs tabular-nums">
                <span className="text-up">涨停 {data.limit_up}</span>
                <span className="text-down">跌停 {data.limit_down}</span>
              </div>
            ) : null}

            {/* 上涨占比（吸底） */}
            <div className="mt-auto flex flex-col gap-1 pt-2">
              <div className="flex items-center justify-between text-xs text-muted-foreground">
                <span>上涨占比</span>
                <span className="text-fg-dim tabular-nums">
                  {upPct != null ? `${upPct}%` : "—"}
                </span>
              </div>
              <Progress value={upPct ?? 0} />
              {dateLabel ? (
                <div className="pt-1 text-right text-[10px] text-muted-foreground">
                  截至 {dateLabel}
                </div>
              ) : null}
            </div>
          </>
        ) : (
          <EmptyState compact title="无数据" className="h-[180px] w-full" />
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
  const byMarket = new Map(summary.map((s) => [s.market, s]));

  // 指数报价并发取（失败降级为 null，卡内隐藏该行）
  const quotes = await Promise.all(
    MARKET_DEFS.map((def) => fetchIndexQuote(def.indexSymbol))
  );

  const anyData = summary.some(
    (s) => s.up > 0 || s.down > 0 || s.flat > 0
  );

  return (
    <section>
      <h2 className="mb-3 text-sm font-medium text-fg-dim">市场情绪总览</h2>
      {anyData ? (
        <div className="grid grid-cols-1 items-stretch gap-4 md:grid-cols-3">
          {MARKET_DEFS.map((def, i) => (
            <SentimentCard
              key={def.market}
              label={def.label}
              indexName={def.indexName}
              data={byMarket.get(def.market)}
              quote={quotes[i]}
            />
          ))}
        </div>
      ) : (
        <Card
          size="sm"
          className="@container/card flex h-40 items-center justify-center bg-linear-to-t from-primary/5 to-card shadow-xs dark:bg-card"
        >
          <EmptyState compact title="等待市场情绪数据" />
        </Card>
      )}
    </section>
  );
}
