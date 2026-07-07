/**
 * 大盘指数总览组件
 * 数据：通过 OpenBB API 拉 yfinance 指数历史，取最新收盘价
 * 指数用 quote 接口 last_price 为 null，改用 historical 取最新收盘
 */
import {
  getIndexHistorical,
  getEquityHistorical,
  type HistoricalPrice,
} from "@/lib/openbb";
import { fmtPrice, fmtPct } from "@/lib/format";

// 全球大盘指数 watchlist（yfinance 代码）
const ALL_INDICES = [
  { symbol: "^GSPC", name: "标普500", market: "us", type: "index" as const },
  { symbol: "^IXIC", name: "纳斯达克", market: "us", type: "index" as const },
  { symbol: "^DJI", name: "道琼斯", market: "us", type: "index" as const },
  { symbol: "^HSI", name: "恒生指数", market: "hk", type: "index" as const },
  { symbol: "^HSCEI", name: "恒生国企", market: "hk", type: "index" as const },
  { symbol: "000001.SS", name: "上证指数", market: "cn", type: "equity" as const },
  { symbol: "399001.SZ", name: "深证成指", market: "cn", type: "equity" as const },
  { symbol: "399006.SZ", name: "创业板指", market: "cn", type: "equity" as const },
];

const MARKET_LABEL: Record<string, string> = {
  us: "US",
  hk: "HK",
  cn: "CN",
};

interface IndexQuote {
  symbol: string;
  cnName: string;
  market: string;
  last_price: number | null;
  change_percent: number | null;
  currency: string | null;
}

// 拉近 7 天历史，取最新 2 条算涨跌幅
async function fetchIndexQuote(
  symbol: string,
  type: "index" | "equity"
): Promise<{ price: number | null; changePct: number | null }> {
  const end = new Date();
  const start = new Date(end.getTime() - 7 * 24 * 60 * 60 * 1000);
  const fmt = (d: Date) => d.toISOString().slice(0, 10);

  try {
    const hist =
      type === "index"
        ? await getIndexHistorical(symbol, fmt(start), fmt(end), "yfinance")
        : await getEquityHistorical(symbol, fmt(start), fmt(end), "yfinance");

    if (hist.length === 0) return { price: null, changePct: null };

    const last = hist[hist.length - 1];
    const prev = hist.length > 1 ? hist[hist.length - 2] : last;
    const changePct =
      prev.close > 0 ? (last.close - prev.close) / prev.close : 0;

    return { price: last.close, changePct };
  } catch (err) {
    console.error(`fetchIndexQuote ${symbol} failed:`, err);
    return { price: null, changePct: null };
  }
}

async function fetchIndices(market: string = "global"): Promise<IndexQuote[]> {
  const indices = market === "global"
    ? ALL_INDICES
    : ALL_INDICES.filter((i) => i.market === market);

  const results = await Promise.all(
    indices.map(async (idx) => {
      const { price, changePct } = await fetchIndexQuote(idx.symbol, idx.type);
      return {
        symbol: idx.symbol,
        cnName: idx.name,
        market: idx.market,
        last_price: price,
        change_percent: changePct,
        currency: null,
      };
    })
  );
  return results;
}

function IndexCard({ quote }: { quote: IndexQuote }) {
  const up = (quote.change_percent ?? 0) >= 0;
  const changeColor = up ? "text-up" : "text-down";
  const arrow = up ? "▲" : "▼";

  return (
    <div className="relative overflow-hidden rounded-lg border border-border bg-panel-2 px-3 py-2.5">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-1.5">
          <span className="rounded-sm bg-border/60 px-1 text-[9px] uppercase tracking-wider text-muted">
            {MARKET_LABEL[quote.market] ?? quote.market}
          </span>
          <span className="text-xs font-medium text-fg-dim">{quote.cnName}</span>
        </div>
        <span className={`text-[10px] ${changeColor}`}>{arrow}</span>
      </div>
      <div className="mt-2 flex items-baseline gap-2">
        <span className={`tab-nums text-xl font-semibold ${changeColor}`}>
          {fmtPrice(quote.last_price)}
        </span>
      </div>
      <div className="mt-1 flex items-center justify-between">
        <span className={`tab-nums text-xs font-medium ${changeColor}`}>
          {fmtPct(quote.change_percent)}
        </span>
      </div>
    </div>
  );
}

export async function MarketOverview({ market = "global" }: { market?: string }) {
  const indices = await fetchIndices(market);

  if (indices.length === 0) {
    return (
      <div className="flex h-48 items-center justify-center rounded-lg border border-border bg-panel text-muted">
        等待指数数据...
      </div>
    );
  }

  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">
      {indices.map((quote) => (
        <IndexCard key={quote.symbol} quote={quote} />
      ))}
    </div>
  );
}
