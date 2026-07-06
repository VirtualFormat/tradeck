import Link from "next/link";
import { MarketOverview } from "@/components/market-overview";
import { StockSearch } from "@/components/stock-search";

export default function Home() {
  return (
    <main className="min-h-screen bg-bg text-fg">
      <div className="mx-auto max-w-7xl px-4 py-6">
        <header className="mb-6 flex items-center justify-between border-b border-border pb-3">
          <div>
            <h1 className="text-lg font-semibold tracking-wide">tradeck</h1>
            <p className="text-[10px] uppercase tracking-[0.18em] text-muted">
              Market Dashboard · Global
            </p>
          </div>
          <div className="flex items-center gap-4">
            <Link href="/news" className="text-xs text-muted hover:text-fg">
              新闻流 →
            </Link>
            <Link href="/macro" className="text-xs text-muted hover:text-fg">
              宏观 →
            </Link>
            <StockSearch />
            <div className="text-[10px] text-muted">
              OpenBB · yfinance
            </div>
          </div>
        </header>

        <section className="mb-6">
          <h2 className="mb-3 text-sm font-medium text-fg-dim">大盘指数</h2>
          {/* @ts-expect-error Server Component */}
          <MarketOverview />
        </section>
      </div>
    </main>
  );
}
