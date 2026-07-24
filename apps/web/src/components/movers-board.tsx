/**
 * 涨跌幅榜 + 活跃榜组件
 * 数据：OpenBB discovery gainers / losers / active
 * 美股/全球：yfinance discovery
 * A 股/港股：预定义列表 + 批量报价
 */
import Link from "next/link";
import { getAggregatedNews, getEquityQuotes } from "@/lib/openbb";
import { StockPreviewTrigger } from "@/components/stock-preview-dialog";
import { EmptyState } from "@/components/empty-state";
import { Badge } from "@/components/ui/badge";
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
  /** 换手率（成交额/市值，仅换手榜有） */
  turnover?: number | null;
}

// A 股热门列表（按市值选）
const CN_STOCKS = [
  "600519.SS", "601318.SS", "600036.SS", "000858.SZ",
  "002594.SZ", "300750.SZ", "601012.SS", "600900.SS",
  "000001.SZ", "601166.SS", "600276.SS", "601398.SS",
];

// 港股热门列表
const HK_STOCKS = [
  "0700.HK", "9988.HK", "0005.HK", "1299.HK",
  "0883.HK", "0939.HK", "0388.HK", "2318.HK",
  "0941.HK", "1810.HK", "3690.HK", "9618.HK",
];

async function fetchScreener(
  type: "gainers" | "losers" | "active",
  market: string = "global",
  date?: string
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

    // 美股/全球用 backend /api/movers（从 DB 读，支持 date 快照回看）
    const BACKEND_API_URL =
      process.env.BACKEND_API_URL ?? "http://localhost:8080";
    const dateQuery = date ? `&date=${date}` : "";
    const res = await fetch(
      `${BACKEND_API_URL}/api/movers?type=${type}&market=US&limit=10${dateQuery}`,
      { headers: { Accept: "application/json" } }
    );
    if (!res.ok) return [];
    const data = await res.json();
    return Array.isArray(data) ? data : [];
  } catch {
    return [];
  }
}

/** 换手榜（backend 计算：成交额/市值，缺市值的标的不计） */
async function fetchTurnover(market: string): Promise<ScreenerItem[]> {
  try {
    const BACKEND_API_URL =
      process.env.BACKEND_API_URL ?? "http://localhost:8080";
    const m = market === "cn" ? "CN" : market === "hk" ? "HK" : "US";
    const res = await fetch(
      `${BACKEND_API_URL}/api/movers/turnover?market=${m}&limit=10`,
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
  metric,
}: {
  item: ScreenerItem;
  metric?: "amount" | "turnover";
}) {
  const up = (item.percent_change ?? 0) >= 0;
  return (
    <StockPreviewTrigger symbol={item.symbol} name={item.name}>
      <div className="flex items-center justify-between border-b border-border/40 py-1.5 transition-colors hover:bg-panel/50 -mx-1 px-1 rounded-sm last:border-0">
        <div className="flex min-w-0 flex-1 items-center gap-2">
          <span className="shrink-0 text-xs font-medium">{item.symbol}</span>
          <span className="truncate text-[10px] text-muted">
            {item.name ?? "—"}
          </span>
        </div>
        <div className="flex shrink-0 items-center gap-3">
          {metric === "amount" ? (
            <span className="tab-nums text-[10px] text-muted">
              {fmtVolume((item.volume ?? 0) * (item.price ?? 0))}
            </span>
          ) : null}
          {metric === "turnover" ? (
            <span className="tab-nums text-[10px] text-accent">
              {item.turnover != null
                ? `${(item.turnover * 100).toFixed(2)}%`
                : "—"}
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
      </div>
    </StockPreviewTrigger>
  );
}

function ScreenerColumn({
  title,
  items,
  href,
  colorClass,
  metric,
}: {
  title: string;
  items: ScreenerItem[];
  href: string;
  colorClass: string;
  metric?: "amount" | "turnover";
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
            <StockRow key={item.symbol} item={item} metric={metric} />
          ))
        ) : (
          <EmptyState compact title="无数据" />
        )}
      </CardContent>
    </Card>
  );
}

export async function MoversBoard({
  market = "global",
  date,
}: {
  market?: string;
  date?: string;
}) {
  const [gainers, losers, active, turnover] = await Promise.all([
    fetchScreener("gainers", market, date),
    fetchScreener("losers", market, date),
    fetchScreener("active", market, date),
    fetchTurnover(market),
  ]);

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <ScreenerColumn
        title="涨幅榜 Top 8"
        items={gainers.slice(0, 8)}
        href="/screener"
        colorClass="text-up"
      />
      <ScreenerColumn
        title="跌幅榜 Top 8"
        items={losers.slice(0, 8)}
        href="/screener"
        colorClass="text-down"
      />
      <ScreenerColumn
        title="活跃榜 Top 8（成交额）"
        items={active.slice(0, 8)}
        href="/screener"
        colorClass="text-accent"
        metric="amount"
      />
      <ScreenerColumn
        title="换手榜 Top 8"
        items={turnover.slice(0, 8)}
        href="/screener"
        colorClass="text-warn"
        metric="turnover"
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
                <Badge
                  variant="secondary"
                  className="mt-0.5 shrink-0 rounded-sm px-1 py-0 text-[9px]"
                >
                  {article.symbol}
                </Badge>
                <span className="text-xs text-fg-dim line-clamp-2 leading-snug">
                  {article.title}
                </span>
              </div>
            </a>
          ))
        ) : (
          <EmptyState compact title="无新闻" />
        )}
      </CardContent>
    </Card>
  );
}
