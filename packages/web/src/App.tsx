import { useQuotes, useFeed } from './api.js';
import type { MarketTick, FeedItem } from '@tradeck/shared';

export function App() {
  const quotes = useQuotes();
  const feed = useFeed();

  return (
    <div className="min-h-full flex flex-col">
      <Header
        fetchedAt={quotes.data?.fetchedAt}
        source={quotes.data?.ticks[0]?.source}
        loading={quotes.isFetching}
      />
      <main className="flex-1 grid grid-cols-1 lg:grid-cols-[1fr_360px] gap-4 p-4">
        <section>
          <SectionTitle>市场行情</SectionTitle>
          {quotes.isLoading ? (
            <SkeletonGrid />
          ) : quotes.isError ? (
            <ErrorBox msg="行情加载失败" />
          ) : (
            <div className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-4 gap-3">
              {quotes.data!.ticks.map((t) => (
                <QuoteCard key={t.symbol} tick={t} />
              ))}
            </div>
          )}
        </section>

        <aside>
          <SectionTitle>资讯流</SectionTitle>
          {feed.isLoading ? (
            <div className="text-term-muted text-sm">加载中…</div>
          ) : feed.isError ? (
            <ErrorBox msg="资讯加载失败" />
          ) : (
            <ul className="space-y-2">
              {feed.data!.items.map((it) => (
                <FeedRow key={it.id} item={it} />
              ))}
            </ul>
          )}
        </aside>
      </main>
    </div>
  );
}

function Header({
  fetchedAt,
  source,
  loading,
}: {
  fetchedAt?: number;
  source?: string;
  loading: boolean;
}) {
  return (
    <header className="flex items-center justify-between px-4 py-3 border-b border-term-border bg-term-panel">
      <div className="flex items-baseline gap-3">
        <span className="text-term-accent font-bold tracking-wider">TRADECK</span>
        <span className="text-term-muted text-xs">市场行情看板</span>
      </div>
      <div className="text-xs text-term-muted flex items-center gap-3">
        {source && (
          <span className={source === 'mock' ? 'text-term-down' : 'text-term-up'}>
            源: {source === 'mock' ? 'MOCK(兜底)' : source.toUpperCase()}
          </span>
        )}
        <span className={loading ? 'animate-pulse' : ''}>
          {fetchedAt ? new Date(fetchedAt).toLocaleTimeString('zh-CN') : '—'}
        </span>
      </div>
    </header>
  );
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="text-xs uppercase tracking-widest text-term-muted mb-3">{children}</h2>
  );
}

function QuoteCard({ tick }: { tick: MarketTick }) {
  const pct = tick.changePercent ?? 0;
  const up = pct >= 0;
  const color = up ? 'text-term-up' : 'text-term-down';
  return (
    <div className="bg-term-panel border border-term-border rounded-md p-3 hover:border-term-accent/50 transition-colors">
      <div className="flex items-baseline justify-between">
        <span className="text-sm text-term-text truncate">{tick.name ?? tick.symbol}</span>
        <span className="text-[10px] text-term-muted">{tick.symbol}</span>
      </div>
      <div className="mt-2 text-xl font-semibold tabular-nums">
        {tick.price.toLocaleString('en-US', { maximumFractionDigits: 2 })}
      </div>
      <div className={`mt-1 text-sm tabular-nums ${color}`}>
        {up ? '▲' : '▼'} {tick.change?.toFixed(2) ?? '—'} ({up ? '+' : ''}
        {pct.toFixed(2)}%)
      </div>
    </div>
  );
}

function FeedRow({ item }: { item: FeedItem }) {
  return (
    <li className="border-b border-term-border/60 pb-2">
      <a
        href={item.url}
        target="_blank"
        rel="noreferrer"
        className="text-sm text-term-text hover:text-term-accent leading-snug block"
      >
        {item.title}
      </a>
      <div className="mt-1 text-[10px] text-term-muted flex gap-2">
        <span>{item.source}</span>
        {item.publishedAt && <span>{new Date(item.publishedAt).toLocaleString('zh-CN')}</span>}
      </div>
    </li>
  );
}

function SkeletonGrid() {
  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-4 gap-3">
      {Array.from({ length: 8 }).map((_, i) => (
        <div key={i} className="bg-term-panel border border-term-border rounded-md p-3 h-24 animate-pulse" />
      ))}
    </div>
  );
}

function ErrorBox({ msg }: { msg: string }) {
  return (
    <div className="text-term-down text-sm border border-term-down/40 rounded-md p-3 bg-term-down/5">
      {msg}
    </div>
  );
}
