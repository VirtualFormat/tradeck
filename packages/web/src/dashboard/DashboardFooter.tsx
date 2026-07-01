import { useFeed } from '../api/useFeed';
import { useTickers } from '../api/useTickers';

export function DashboardFooter(): JSX.Element {
  const { data: tickers } = useTickers();
  const { data: feed } = useFeed(30);
  const sources = new Set((tickers ?? []).map((t) => t.source));

  return (
    <footer className="flex flex-wrap items-center gap-x-6 gap-y-1 text-[11px] text-muted px-2 py-2.5">
      <span className="flex items-center gap-1.5">
        <span className="w-1.5 h-1.5 rounded-full bg-up shadow-[0_0_6px_var(--color-up)]" />
        系统在线 · online
      </span>
      <span className="tab-nums">{sources.size} sources</span>
      <span className="tab-nums">{tickers?.length ?? 0} symbols</span>
      <span className="tab-nums">{feed?.length ?? 0} feed items</span>
      <span>transport · polling</span>
      <span className="ml-auto opacity-80">stack · React · Hono · Cloudflare Workers</span>
    </footer>
  );
}
