import { MarketOverview } from "@/components/market-overview";

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
          <div className="text-[10px] text-muted">
            数据源：OpenBB Platform · yfinance
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
