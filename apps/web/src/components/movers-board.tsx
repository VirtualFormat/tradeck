/**
 * 涨跌幅榜 + 活跃榜组件
 * 数据：OpenBB discovery gainers / losers / active
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

async function fetchScreener(
  type: "gainers" | "losers" | "active"
): Promise<ScreenerItem[]> {
  try {
    const res = await fetch(
      `${OPENBB_API_URL}/api/v1/equity/discovery/${type}?provider=yfinance`,
      { next: { revalidate: 300 }, headers: { Accept: "application/json" } }
    );
    if (!res.ok) return [];
    const text = await res.text();
    if (!text) return [];
    const data = JSON.parse(text);
    return (data.results ?? []).slice(0, 10);
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
    <div>
      <div className="mb-2 flex items-center justify-between">
        <h3 className={`text-xs font-medium ${colorClass}`}>{title}</h3>
        <Link href={href} className="text-[10px] text-muted hover:text-fg">
          更多 →
        </Link>
      </div>
      <div className="rounded-lg border border-border bg-panel-2 px-3 py-1">
        {items.length > 0 ? (
          items.map((item) => (
            <StockRow key={item.symbol} item={item} showVolume={showVolume} />
          ))
        ) : (
          <div className="py-4 text-center text-[10px] text-muted">
            无数据
          </div>
        )}
      </div>
    </div>
  );
}

export async function MoversBoard() {
  const [gainers, losers, active] = await Promise.all([
    fetchScreener("gainers"),
    fetchScreener("losers"),
    fetchScreener("active"),
  ]);

  return (
    <div className="space-y-4">
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
export async function TopNews() {
  const articles = await getAggregatedNews(["AAPL", "MSFT", "NVDA", "TSLA"], 1);
  const top4 = articles.slice(0, 4);

  return (
    <div>
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-xs font-medium text-fg-dim">热门资讯</h3>
        <Link href="/news" className="text-[10px] text-muted hover:text-fg">
          更多 →
        </Link>
      </div>
      <div className="rounded-lg border border-border bg-panel-2 px-3 py-1">
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
      </div>
    </div>
  );
}
