import { useMemo } from 'react';
import { Card } from './widgets/Card';
import { CardGridSkeleton } from './widgets/Skeleton';
import { useTickers } from '../api/useTickers';
import { filterByMarket, type Market } from './market';

function fmtPrice(p: number): string {
  return p.toLocaleString('en-US', { maximumFractionDigits: p >= 100 ? 2 : 4 });
}

/** Faint background area+line drawn behind the card text. */
function Sparkline({ data, up }: { data: number[]; up: boolean }): JSX.Element | null {
  const W = 100;
  const H = 40;
  if (data.length < 2) return null;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const span = max - min || 1;
  const pts = data.map((v, i) => {
    const x = (i / (data.length - 1)) * W;
    const y = H - ((v - min) / span) * (H - 4) - 2; // 2px padding top/bottom
    return [x, y] as const;
  });
  const line = pts.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(' ');
  const area = `0,${H} ${line} ${W},${H}`;
  const color = up ? 'var(--color-up)' : 'var(--color-down)';

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      preserveAspectRatio="none"
      className="pointer-events-none absolute inset-x-0 bottom-0 h-[58%] w-full"
      aria-hidden
    >
      <polygon points={area} fill={color} opacity="0.1" />
      <polyline
        points={line}
        fill="none"
        stroke={color}
        strokeWidth="1.5"
        strokeLinejoin="round"
        strokeLinecap="round"
        opacity="0.7"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
}

export function MarketOverview({ market }: { market: Market }): JSX.Element {
  const { data, isLoading } = useTickers();

  const rows = useMemo(() => {
    const list = filterByMarket(data, market);
    // a symbol served by >1 source gets disambiguated by source prefix
    const symbolCount = new Map<string, number>();
    for (const t of list) symbolCount.set(t.symbol, (symbolCount.get(t.symbol) ?? 0) + 1);
    return list
      .slice()
      .sort((a, b) => b.changePct - a.changePct)
      .map((t) => {
        const base = t.name ?? t.symbol;
        return {
          ...t,
          label: (symbolCount.get(t.symbol) ?? 0) > 1 ? `${t.source}:${base}` : base,
        };
      });
  }, [data, market]);

  return (
    <Card title="行情总览" subtitle="Market Overview" corner="live">
      {isLoading && <CardGridSkeleton />}
      {/* single non-wrapping row; scrolls horizontally if it can't all fit */}
      <div className="scroll-thin flex h-full items-stretch gap-2 overflow-x-auto">
        {rows.map((t) => {
          const up = t.changePct >= 0;
          return (
            <div
              key={`${t.source}:${t.symbol}`}
              className="group relative flex min-w-[150px] flex-1 flex-col overflow-hidden rounded-md border border-border bg-panel-2 p-2.5 transition-colors hover:border-border-strong"
            >
              {/* left accent edge keyed to direction */}
              <span
                className={`absolute inset-y-0 left-0 w-[3px] ${up ? 'bg-up/70' : 'bg-down/70'}`}
              />
              <Sparkline data={t.spark} up={up} />
              {/* content sits above the sparkline */}
              <div className="relative z-10">
                <div className="flex items-center justify-between gap-1">
                  <span className="truncate text-[11px] text-fg-dim">{t.label}</span>
                  <span
                    className={`tab-nums shrink-0 text-[10px] ${up ? 'text-up' : 'text-down'}`}
                  >
                    {up ? '▲' : '▼'} {Math.abs(t.changePct * 100).toFixed(2)}%
                  </span>
                </div>
                <div
                  className={`tab-nums mt-1 text-lg leading-none ${up ? 'text-up' : 'text-down'}`}
                >
                  {fmtPrice(t.price)}
                </div>
                <div className="mt-1 text-[8.5px] uppercase tracking-[0.15em] text-muted">
                  {t.source}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </Card>
  );
}
