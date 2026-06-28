import { useMemo } from 'react';
import { Card } from './widgets/Card';
import { CardGridSkeleton } from './widgets/Skeleton';
import { useTickers } from '../api/useTickers';

function fmtPrice(p: number): string {
  return p.toLocaleString('en-US', { maximumFractionDigits: p >= 100 ? 2 : 4 });
}

export function MarketOverview(): JSX.Element {
  const { data, isLoading } = useTickers();

  const rows = useMemo(() => {
    const list = data ?? [];
    // a symbol served by >1 source gets disambiguated by source prefix
    const symbolCount = new Map<string, number>();
    for (const t of list) symbolCount.set(t.symbol, (symbolCount.get(t.symbol) ?? 0) + 1);
    return list
      .slice()
      .sort((a, b) => b.changePct - a.changePct)
      .map((t) => ({
        ...t,
        label: (symbolCount.get(t.symbol) ?? 0) > 1 ? `${t.source}:${t.symbol}` : t.symbol,
      }));
  }, [data]);

  return (
    <Card title="行情总览" subtitle="Market Overview" corner="live">
      {isLoading && <CardGridSkeleton />}
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
        {rows.map((t) => {
          const up = t.changePct >= 0;
          return (
            <div
              key={`${t.source}:${t.symbol}`}
              className="group relative overflow-hidden bg-panel-2 border border-border rounded-md p-2.5 transition-colors hover:border-border-strong"
            >
              {/* left accent edge keyed to direction */}
              <span
                className={`absolute inset-y-0 left-0 w-[3px] ${up ? 'bg-up/70' : 'bg-down/70'}`}
              />
              <div className="flex items-center justify-between gap-1">
                <span className="text-fg-dim text-[11px] truncate">{t.label}</span>
                <span
                  className={`tab-nums text-[10px] shrink-0 ${up ? 'text-up' : 'text-down'}`}
                >
                  {up ? '▲' : '▼'} {Math.abs(t.changePct * 100).toFixed(2)}%
                </span>
              </div>
              <div className={`tab-nums text-lg mt-1 leading-none ${up ? 'text-up' : 'text-down'}`}>
                {fmtPrice(t.price)}
              </div>
              <div className="text-muted text-[8.5px] uppercase tracking-[0.15em] mt-1">
                {t.source}
              </div>
            </div>
          );
        })}
      </div>
    </Card>
  );
}
