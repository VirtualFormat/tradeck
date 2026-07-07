/**
 * 涨跌幅榜组件
 * 数据：OpenBB discovery gainers + losers
 * 显示 Top 5，红涨绿跌
 */
import Link from "next/link";
import { getAggregatedNews } from "@/lib/openbb";

interface ScreenerItem {
  symbol: string;
  name: string | null;
  price: number | null;
  change: number | null;
  percent_change: number | null;
  volume: number | null;
}

const OPENBB_API_URL =
  process.env.OPENBB_API_URL ?? "http://localhost:6900";

async function fetchScreener(type: "gainers" | "losers"): Promise<ScreenerItem[]> {
  try {
    const res = await fetch(
      `${OPENBB_API_URL}/api/v1/equity/discovery/${type}?provider=yfinance`,
      { next: { revalidate: 300 }, headers: { Accept: "application/json" } }
    );
    if (!res.ok) return [];
    const text = await res.text();
    if (!text) return [];
    const data = JSON.parse(text);
    return (data.results ?? []).slice(0, 5);
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

function StockRow({ item }: { item: ScreenerItem }) {
  const up = (item.percent_change ?? 0) >= 0;
  return (
    <Link
      href={`/stocks/${item.symbol}`}
      className="flex items-center justify-between border-b border-border/40 py-1.5 transition-colors hover:bg-panel-2/50 -mx-1 px-1 rounded-sm"
    >
      <div className="flex min-w-0 flex-1 items-center gap-2">
        <span className="shrink-0 text-xs font-medium">{item.symbol}</span>
        <span className="truncate text-[10px] text-muted">
          {item.name ?? "—"}
        </span>
      </div>
      <div className="flex shrink-0 items-center gap-3">
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

export async function MoversBoard() {
  const [gainers, losers] = await Promise.all([
    fetchScreener("gainers"),
    fetchScreener("losers"),
  ]);

  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
      <div>
        <div className="mb-2 flex items-center justify-between">
          <h3 className="text-xs font-medium text-up">涨幅榜 Top 5</h3>
          <Link
            href="/screener"
            className="text-[10px] text-muted hover:text-fg"
          >
            更多 →
          </Link>
        </div>
        <div className="rounded-lg border border-border bg-panel-2 px-3 py-1">
          {gainers.length > 0 ? (
            gainers.map((item) => (
              <StockRow key={item.symbol} item={item} />
            ))
          ) : (
            <div className="py-4 text-center text-[10px] text-muted">
              无数据
            </div>
          )}
        </div>
      </div>

      <div>
        <div className="mb-2 flex items-center justify-between">
          <h3 className="text-xs font-medium text-down">跌幅榜 Top 5</h3>
          <Link
            href="/screener"
            className="text-[10px] text-muted hover:text-fg"
          >
            更多 →
          </Link>
        </div>
        <div className="rounded-lg border border-border bg-panel-2 px-3 py-1">
          {losers.length > 0 ? (
            losers.map((item) => (
              <StockRow key={item.symbol} item={item} />
            ))
          ) : (
            <div className="py-4 text-center text-[10px] text-muted">
              无数据
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// 热门新闻（3 条）
export async function TopNews() {
  const articles = await getAggregatedNews(["AAPL", "MSFT", "NVDA", "TSLA"], 1);
  const top3 = articles.slice(0, 4);

  return (
    <div>
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-xs font-medium text-fg-dim">热门资讯</h3>
        <Link href="/news" className="text-[10px] text-muted hover:text-fg">
          更多 →
        </Link>
      </div>
      <div className="rounded-lg border border-border bg-panel-2 px-3 py-1">
        {top3.length > 0 ? (
          top3.map((article, i) => (
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
      </div>
    </div>
  );
}
