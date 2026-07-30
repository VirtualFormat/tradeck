/** 首页补充指数区：删除情绪卡已经展示的三只旗舰指数，不绘制 Sparkline。 */
import { CompactIndexCard } from "@/components/dashboard/compact-index-card";
import { EmptyState } from "@/components/empty-state";
import { Card } from "@/components/ui/card";
import { fmtDataDate } from "@/lib/format";
import { getIndexHistorical } from "@/lib/openbb";

type MarketKey = "cn" | "us" | "hk";

const MARKET_GROUPS: {
  key: MarketKey;
  label: string;
  indices: { symbol: string; name: string }[];
}[] = [
  {
    key: "cn",
    label: "A股",
    indices: [
      { symbol: "399001.SZ", name: "深证成指" },
      { symbol: "399006.SZ", name: "创业板指" },
    ],
  },
  {
    key: "us",
    label: "美股",
    indices: [
      { symbol: "^IXIC", name: "纳斯达克" },
      { symbol: "^DJI", name: "道琼斯" },
    ],
  },
  {
    key: "hk",
    label: "港股",
    indices: [{ symbol: "^HSCEI", name: "恒生国企" }],
  },
];

interface CompactIndexQuote {
  symbol: string;
  name: string;
  price: number | null;
  changePct: number | null;
  date: string | null;
}

async function fetchIndexQuote(symbol: string): Promise<{
  price: number | null;
  changePct: number | null;
  date: string | null;
}> {
  const end = new Date();
  const start = new Date(end.getTime() - 14 * 24 * 60 * 60 * 1000);
  const fmt = (date: Date) => date.toISOString().slice(0, 10);

  try {
    const hist = await getIndexHistorical(symbol, fmt(start), fmt(end));
    if (hist.length === 0) {
      return { price: null, changePct: null, date: null };
    }

    const last = hist[hist.length - 1];
    const prev = hist.length > 1 ? hist[hist.length - 2] : last;
    return {
      price: last.close,
      changePct:
        prev.close > 0 ? (last.close - prev.close) / prev.close : 0,
      date: last.date,
    };
  } catch (err) {
    console.error(`IndicesByMarket ${symbol} failed:`, err);
    return { price: null, changePct: null, date: null };
  }
}

async function fetchGroupQuotes(
  group: (typeof MARKET_GROUPS)[number]
): Promise<CompactIndexQuote[]> {
  return Promise.all(
    group.indices.map(async (index) => ({
      symbol: index.symbol,
      name: index.name,
      ...(await fetchIndexQuote(index.symbol)),
    }))
  );
}

export async function IndicesByMarket() {
  const groups = await Promise.all(
    MARKET_GROUPS.map(async (group) => ({
      ...group,
      quotes: await fetchGroupQuotes(group),
    }))
  );
  const visibleGroups = groups.filter((group) =>
    group.quotes.some((quote) => quote.price != null)
  );

  if (visibleGroups.length === 0) {
    return (
      <Card className="flex h-28 items-center justify-center">
        <EmptyState compact title="等待指数数据" />
      </Card>
    );
  }

  return (
    <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
      {visibleGroups.map((group) => {
        const latestDate = group.quotes
          .map((quote) => quote.date)
          .filter((value): value is string => Boolean(value))
          .sort()
          .pop();
        const dateLabel = fmtDataDate(latestDate);
        const distinctDates = new Set(
          group.quotes
            .map((quote) => quote.date)
            .filter((value): value is string => Boolean(value))
        );
        const datePrefix = distinctDates.size > 1 ? "截至 " : "";

        return (
          <section key={group.key} className="min-w-0">
            <div className="mb-2 flex items-baseline justify-between gap-2">
              <h3 className="text-xs font-medium text-fg-dim">{group.label}</h3>
              {dateLabel ? (
                <span className="text-[11px] text-muted-foreground tabular-nums">
                  最新 · {datePrefix}{dateLabel}
                </span>
              ) : null}
            </div>
            <div
              className={
                group.quotes.length === 1
                  ? "grid grid-cols-1 gap-2.5"
                  : "grid grid-cols-2 gap-2.5"
              }
            >
              {group.quotes.map((quote) => (
                <CompactIndexCard
                  key={quote.symbol}
                  name={quote.name}
                  price={quote.price}
                  changePct={quote.changePct}
                />
              ))}
            </div>
          </section>
        );
      })}
    </div>
  );
}
