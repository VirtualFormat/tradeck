/**
 * 大盘指数（分市场分组）—— 服务端组件
 * - 复用 market-overview.tsx 的指数取数逻辑（getIndexHistorical / getEquityHistorical）
 *   与 IndexCard 卡片。分 A股 / 美股 / 港股 三组，每组小标题 + 该组指数横排（响应式换行）。
 * - 数据用真实 fetcher，取不到的组/指数优雅降级（组内无数据则隐藏该组）。
 */
import { getIndexHistorical, getEquityHistorical } from "@/lib/openbb";
import { IndexCard, type IndexQuote } from "@/components/index-card";
import { EmptyState } from "@/components/empty-state";
import { Card } from "@/components/ui/card";
import { fmtDataDate } from "@/lib/format";

type MarketKey = "cn" | "us" | "hk";

// 各市场指数定义（symbol 沿用 market-overview 中已验证可用的 yfinance 代码）
const MARKET_GROUPS: {
  key: MarketKey;
  label: string;
  indices: {
    symbol: string;
    name: string;
    type: "index" | "equity";
  }[];
}[] = [
  {
    key: "cn",
    label: "A股",
    indices: [
      { symbol: "000001.SS", name: "上证指数", type: "index" },
      { symbol: "399001.SZ", name: "深证成指", type: "index" },
      { symbol: "399006.SZ", name: "创业板指", type: "index" },
    ],
  },
  {
    key: "us",
    label: "美股",
    indices: [
      { symbol: "^GSPC", name: "标普500", type: "index" },
      { symbol: "^IXIC", name: "纳斯达克", type: "index" },
      { symbol: "^DJI", name: "道琼斯", type: "index" },
    ],
  },
  {
    key: "hk",
    label: "港股",
    indices: [
      { symbol: "^HSI", name: "恒生指数", type: "index" },
      { symbol: "^HSCEI", name: "恒生国企", type: "index" },
    ],
  },
];

// 拉近 14 日历史，取最新 2 条算涨跌幅 + 近 7 日序列给卡片 mini chart
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

async function fetchGroupQuotes(
  group: (typeof MARKET_GROUPS)[number]
): Promise<IndexQuote[]> {
  const results = await Promise.all(
    group.indices.map(async (idx) => {
      const { price, changePct, hist } = await fetchIndexQuoteAndHist(
        idx.symbol,
        idx.type
      );
      return {
        symbol: idx.symbol,
        cnName: idx.name,
        market: group.key,
        last_price: price,
        change_percent: changePct,
        currency: null,
        hist,
      } satisfies IndexQuote;
    })
  );
  return results;
}

export async function IndicesByMarket() {
  const groups = await Promise.all(
    MARKET_GROUPS.map(async (group) => ({
      ...group,
      quotes: await fetchGroupQuotes(group),
    }))
  );

  // 仅保留至少有一条有效价格的组（优雅降级：整组取不到则隐藏）
  const visibleGroups = groups.filter((g) =>
    g.quotes.some((q) => q.last_price != null)
  );

  if (visibleGroups.length === 0) {
    return (
      <Card className="flex h-32 items-center justify-center">
        <EmptyState compact title="等待指数数据" />
      </Card>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      {visibleGroups.map((group) => {
        // 该组最新交易日：取组内各指数历史序列中最大的日期
        const latestDate = group.quotes
          .map((q) => q.hist?.[q.hist.length - 1]?.date)
          .filter((d): d is string => Boolean(d))
          .sort()
          .pop();
        const dateLabel = fmtDataDate(latestDate);

        return (
          <div key={group.key}>
            <div className="mb-3 flex items-baseline justify-between gap-2">
              <h3 className="text-sm font-medium text-fg-dim">{group.label}</h3>
              {dateLabel && (
                <span className="text-xs text-muted-foreground tabular-nums">
                  {dateLabel}
                </span>
              )}
            </div>
            <div className="grid grid-cols-2 gap-3 *:data-[slot=card]:bg-linear-to-t *:data-[slot=card]:from-primary/5 *:data-[slot=card]:to-card *:data-[slot=card]:shadow-xs sm:grid-cols-3 lg:grid-cols-4 dark:*:data-[slot=card]:bg-card">
              {group.quotes.map((quote) => (
                <IndexCard key={quote.symbol} quote={quote} />
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}
