/**
 * 大盘指数总览组件（服务端）
 * - 数据：通过 backend API 拉指数历史，取最新收盘价 + 近 7 日 mini 走势
 * - UI：grid of IndexCard（shadcn Card + phosphor icons，hover 显示具体数值）
 * - 保留 block SectionCards 风格（grid 渐变背景）
 */
import { getIndexHistorical, getEquityHistorical } from "@/lib/openbb";
import { Card } from "@/components/ui/card";
import { IndexCard, type IndexQuote } from "@/components/index-card";
import { EmptyState } from "@/components/empty-state";

// 全球大盘指数 watchlist（yfinance 代码）
const ALL_INDICES = [
  { symbol: "^GSPC", name: "标普500", market: "us", type: "index" as const },
  { symbol: "^IXIC", name: "纳斯达克", market: "us", type: "index" as const },
  { symbol: "^DJI", name: "道琼斯", market: "us", type: "index" as const },
  { symbol: "^HSI", name: "恒生指数", market: "hk", type: "index" as const },
  { symbol: "^HSCEI", name: "恒生国企", market: "hk", type: "index" as const },
  { symbol: "000001.SS", name: "上证指数", market: "cn", type: "index" as const },
  { symbol: "399001.SZ", name: "深证成指", market: "cn", type: "index" as const },
  { symbol: "399006.SZ", name: "创业板指", market: "cn", type: "index" as const },
];

// 拉近 14 日历史，取最新 2 条算涨跌幅 + 近 7 日序列传给卡片 mini chart
async function fetchIndexQuoteAndHist(
  symbol: string,
  type: "index" | "equity"
): Promise<{
  price: number | null;
  changePct: number | null;
  hist: { date: string; value: number }[];
}> {
  const end = new Date();
  const start = new Date(end.getTime() - 14 * 24 * 60 * 60 * 1000);
  const fmt = (d: Date) => d.toISOString().slice(0, 10);

  try {
    const hist =
      type === "index"
        ? await getIndexHistorical(symbol, fmt(start), fmt(end))
        : await getEquityHistorical(symbol, fmt(start), fmt(end));

    if (hist.length === 0) return { price: null, changePct: null, hist: [] };

    const last7 = hist.slice(-7);
    const last = last7[last7.length - 1];
    const prev = last7.length > 1 ? last7[last7.length - 2] : last;
    const changePct = prev.close > 0 ? (last.close - prev.close) / prev.close : 0;

    return {
      price: last.close,
      changePct,
      hist: last7.map((p) => ({ date: p.date, value: p.close })),
    };
  } catch (err) {
    console.error(`fetchIndexQuoteAndHist ${symbol} failed:`, err);
    return { price: null, changePct: null, hist: [] };
  }
}

async function fetchIndices(market: string = "global"): Promise<IndexQuote[]> {
  const indices =
    market === "global"
      ? ALL_INDICES
      : ALL_INDICES.filter((i) => i.market === market);

  const results = await Promise.all(
    indices.map(async (idx) => {
      const { price, changePct, hist } = await fetchIndexQuoteAndHist(
        idx.symbol,
        idx.type
      );
      return {
        symbol: idx.symbol,
        cnName: idx.name,
        market: idx.market,
        last_price: price,
        change_percent: changePct,
        currency: null,
        hist,
      } satisfies IndexQuote;
    })
  );
  return results;
}

export async function MarketOverview({ market = "global" }: { market?: string }) {
  const indices = await fetchIndices(market);

  if (indices.length === 0) {
    return (
      <Card className="flex h-48 items-center justify-center">
        <EmptyState compact title="等待指数数据" />
      </Card>
    );
  }

  return (
    <div className="grid grid-cols-2 gap-3 *:data-[slot=card]:bg-linear-to-t *:data-[slot=card]:from-primary/5 *:data-[slot=card]:to-card *:data-[slot=card]:shadow-xs @xl/main:grid-cols-4 @5xl/main:grid-cols-8 dark:*:data-[slot=card]:bg-card">
      {indices.map((quote) => (
        <IndexCard key={quote.symbol} quote={quote} />
      ))}
    </div>
  );
}
