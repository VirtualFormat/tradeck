import { Card } from './widgets/Card';
import { useTickers } from '../api/useTickers';

function fmtPrice(p: number): string {
  return p.toLocaleString('en-US', { maximumFractionDigits: p >= 100 ? 2 : 4 });
}

export function MarketOverview(): JSX.Element {
  const { data, isLoading } = useTickers();

  return (
    <Card title="行情总览" subtitle="Market Overview" corner="live">
      {isLoading && <div className="text-muted text-xs">loading…</div>}
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
        {data?.map((t) => {
          const up = t.changePct >= 0;
          return (
            <div
              key={`${t.source}:${t.symbol}`}
              className="bg-panel-2 border border-border rounded p-2.5"
            >
              <div className="flex items-center justify-between">
                <span className="text-fg text-xs truncate">{t.symbol}</span>
                <span className={`tab-nums text-[10px] ${up ? 'text-up' : 'text-down'}`}>
                  {up ? '+' : ''}
                  {(t.changePct * 100).toFixed(2)}%
                </span>
              </div>
              <div className={`tab-nums text-lg mt-1 ${up ? 'text-up' : 'text-down'}`}>
                {fmtPrice(t.price)}
              </div>
              <div className="text-muted text-[9px] uppercase tracking-wider mt-0.5">
                {t.source}
              </div>
            </div>
          );
        })}
      </div>
    </Card>
  );
}
