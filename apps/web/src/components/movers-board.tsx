/**
 * 涨跌幅榜 + 活跃榜组件
 * 数据：OpenBB discovery gainers / losers / active
 * 美股/全球：yfinance discovery
 * A 股/港股：预定义列表 + 批量报价
 */
import Link from "next/link";
import { getAggregatedNews, getEquityQuotes } from "@/lib/openbb";
import { MoversBarChart } from "@/components/movers-bar-chart";
import {
  Card,
  CardAction,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

interface ScreenerItem {
  symbol: string;
  name: string | null;
  price: number | null;
  change: number | null;
  percent_change: number | null;
  volume: number | null;
}

// A 股热门列表（按市值选）
const CN_STOCKS = [
  "600519.SH", "601318.SH", "600036.SH", "000858.SZ",
  "002594.SZ", "300750.SZ", "601012.SH", "600900.SH",
  "000001.SZ", "601166.SH", "600276.SH", "601398.SH",
];

// 港股热门列表
const HK_STOCKS = [
  "0700.HK", "9988.HK", "0005.HK", "1299.HK",
  "0883.HK", "0939.HK", "0388.HK", "2318.HK",
  "0941.HK", "1810.HK", "3690.HK", "9618.HK",
];

async function fetchScreener(
  type: "gainers" | "losers" | "active",
  market: string = "global"
): Promise<ScreenerItem[]> {
  try {
    if (market === "cn" || market === "hk") {
      // A 股/港股用预定义列表 + 批量报价
      const symbols = market === "cn" ? CN_STOCKS : HK_STOCKS;
      const quotes = await getEquityQuotes(symbols);
      const items: ScreenerItem[] = quotes.map((q) => ({
        symbol: q.symbol,
        name: q.name,
        price: q.last_price,
        change: q.change,
        percent_change: q.change_percent,
        volume: q.volume,
      }));
      const sorted = [...items].sort((a, b) => {
        const pa = a.percent_change ?? -999;
        const pb = b.percent_change ?? -999;
        if (type === "gainers") return pb - pa;
        if (type === "losers") return pa - pb;
        return (b.volume ?? 0) - (a.volume ?? 0);
      });
      return sorted.slice(0, 10);
    }

    // 美股/全球用 backend /api/movers（从 DB 读，<10ms）
    const BACKEND_API_URL =
      process.env.BACKEND_API_URL ?? "http://localhost:8080";
    const res = await fetch(
      `${BACKEND_API_URL}/api/movers?type=${type}&market=US&limit=10`,
      { headers: { Accept: "application/json" } }
    );
    if (!res.ok) return [];
    const data = await res.json();
    return Array.isArray(data) ? data : [];
  } catch {
    return [];
  }
}

function fmtPrice(v: number | null | undefined): string {
  if (v == null) return "—";
  if (v >= 1000) return v.toFixed(0);
  if (v >= 100) return v.toFixed(1);
  return v.toFixed(2);
}

function fmtPct(pct: number | null | undefined): string {
  if (pct == null) return "—";
  const sign = pct >= 0 ? "+" : "";
  return `${sign}${(pct * 100).toFixed(2)}%`;
}

function fmtVolume(v: number | null | undefined): string {
  if (v == null) return "—";
  if (v >= 1e9) return `${(v / 1e9).toFixed(2)}B`;
  if (v >= 1e6) return `${(v / 1e6).toFixed(2)}M`;
  if (v >= 1e3) return `${(v / 1e3).toFixed(2)}K`;
  return v.toLocaleString("en-US");
}

function StockRow({
  item,
  showVolume,
}: {
  item: ScreenerItem;
  showVolume?: boolean;
}) {
  const up = (item.percent_change ?? 0) >= 0;
  return (
    <Link
      href={`/stocks/${item.symbol}`}
      className="flex items-center justify-between border-b border-border/40 py-1.5 transition-colors hover:bg-panel/50 -mx-1 px-1 rounded-sm last:border-0"
    >
      <div className="flex min-w-0 flex-1 items-center gap-2">
        <span className="shrink-0 text-xs font-medium">{item.symbol}</span>
        <span className="truncate text-[10px] text-muted">
          {item.name ?? "—"}
        </span>
      </div>
      <div className="flex shrink-0 items-center gap-3">
        {showVolume ? (
          <span className="tab-nums text-[10px] text-muted">
            {fmtVolume(item.volume)}
          </span>
        ) : null}
        <span className="tab-nums text-xs text-fg-dim">
          {fmtPrice(item.price)}
        </span>
        <span
          className={`tab-nums w-16 text-right text-xs ${
            up ? "text-up" : "text-down"
          }`}
        >
          {fmtPct(item.percent_change)}
        </span>
      </div>
    </Link>
  );
}

function ScreenerColumn({
  title,
  items,
  href,
  colorClass,
  showVolume,
}: {
  title: string;
  items: ScreenerItem[];
  href: string;
  colorClass: string;
  showVolume?: boolean;
}) {
  return (
    <Card
      size="sm"
      className="@container/card bg-linear-to-t from-primary/5 to-card shadow-xs dark:bg-card"
    >
      <CardHeader>
        <CardTitle className={`text-base font-medium ${colorClass}`}>
          {title}
        </CardTitle>
        <CardAction>
          <Link href={href} className="text-xs text-muted hover:text-fg">
            更多 →
          </Link>
        </CardAction>
      </CardHeader>
      <CardContent>
        {items.length > 0 ? (
          items.map((item) => (
            <StockRow key={item.symbol} item={item} showVolume={showVolume} />
          ))
        ) : (
          <div className="py-4 text-center text-[10px] text-muted">
            无数据
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export async function MoversBoard({ market = "global" }: { market?: string }) {
  const [gainers, losers, active] = await Promise.all([
    fetchScreener("gainers", market),
    fetchScreener("losers", market),
    fetchScreener("active", market),
  ]);

  return (
    <div className="space-y-4">
      <MoversBarChart gainers={gainers} losers={losers} />
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <ScreenerColumn
          title="涨幅榜 Top 10"
          items={gainers}
          href="/screener"
          colorClass="text-up"
        />
        <ScreenerColumn
          title="跌幅榜 Top 10"
          items={losers}
          href="/screener"
          colorClass="text-down"
        />
      </div>
      <ScreenerColumn
        title="活跃榜 Top 10（成交量）"
        items={active}
        href="/screener"
        colorClass="text-accent"
        showVolume
      />
    </div>
  );
}

// 热门新闻（4 条）
const NEWS_SYMBOLS: Record<string, string[]> = {
  global: ["AAPL", "MSFT", "NVDA", "TSLA"],
  us: ["AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "GOOGL", "META"],
  cn: ["BABA", "PDD", "JD", "BIDU"],  // A 股新闻 yfinance 不支持，用 ADR
  hk: ["0700.HK", "9988.HK", "1810.HK", "3690.HK"],
};

export async function TopNews({ market = "global" }: { market?: string }) {
  const symbols = NEWS_SYMBOLS[market] ?? NEWS_SYMBOLS.global;
  const articles = await getAggregatedNews(symbols, 1);
  const top4 = articles.slice(0, 4);

  return (
    <Card
      size="sm"
      className="@container/card bg-linear-to-t from-primary/5 to-card shadow-xs dark:bg-card"
    >
      <CardHeader>
        <CardTitle className="text-base font-medium text-fg-dim">
          热门资讯
        </CardTitle>
        <CardAction>
          <Link href="/news" className="text-xs text-muted hover:text-fg">
            更多 →
          </Link>
        </CardAction>
      </CardHeader>
      <CardContent>
        {top4.length > 0 ? (
          top4.map((article, i) => (
            <a
              key={i}
              href={article.url}
              target="_blank"
              rel="noopener noreferrer"
              className="block border-b border-border/40 py-1.5 transition-colors hover:bg-panel/50 -mx-1 px-1 rounded-sm last:border-0"
            >
              <div className="flex items-start gap-2">
                <span className="mt-0.5 shrink-0 rounded-sm bg-border/60 px-1 text-[9px] text-muted">
                  {article.symbol}
                </span>
                <span className="text-xs text-fg-dim line-clamp-2 leading-snug">
                  {article.title}
                </span>
              </div>
            </a>
          ))
        ) : (
          <div className="py-4 text-center text-[10px] text-muted">
            无新闻
          </div>
        )}
      </CardContent>
    </Card>
  );
}
