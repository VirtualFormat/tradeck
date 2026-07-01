import { useEffect, useState } from 'react';
import { DATA_SOURCE_MODES, type DataSourceMode, type Market } from './market';
import { MarketTabs } from './widgets/MarketTabs';

function utcClock(): string {
  const d = new Date();
  const p = (n: number) => String(n).padStart(2, '0');
  return `${p(d.getUTCHours())}:${p(d.getUTCMinutes())}:${p(d.getUTCSeconds())}`;
}

interface HeaderProps {
  onOpenSources: () => void;
  editing: boolean;
  onToggleEdit: () => void;
  onSaveLayout: () => void;
  onResetLayout: () => void;
  market: Market;
  onMarketChange: (market: Market) => void;
  sourceMode: DataSourceMode;
  onSourceModeChange: (mode: DataSourceMode) => void;
}

export function DashboardHeader({
  onOpenSources,
  editing,
  onToggleEdit,
  onSaveLayout,
  onResetLayout,
  market,
  onMarketChange,
  sourceMode,
  onSourceModeChange,
}: HeaderProps): JSX.Element {
  const [clock, setClock] = useState(utcClock());

  useEffect(() => {
    const t = setInterval(() => setClock(utcClock()), 1000);
    return () => clearInterval(t);
  }, []);

  return (
    <header className="panel-surface flex items-center justify-between border border-border rounded-card px-4 py-3">
      <div className="flex items-center gap-3">
        <svg width="32" height="32" viewBox="0 0 32 32" className="shrink-0" aria-hidden>
          <rect x="1" y="1" width="30" height="30" rx="8" fill="none" stroke="var(--color-border-strong)" />
          <polyline
            points="7,21 12,15 16,18 21,9 25,13"
            fill="none"
            stroke="var(--color-up)"
            strokeWidth="2"
            strokeLinejoin="round"
            strokeLinecap="round"
          />
          <circle cx="21" cy="9" r="2" fill="var(--color-up)" />
        </svg>
        <div className="leading-tight">
          <div className="text-muted text-[9px] uppercase tracking-[0.28em]">
            实时行情驾驶舱 · live market deck
          </div>
          <div className="text-fg text-[17px] font-semibold tracking-[0.35em]">TRADECK</div>
        </div>
      </div>
      <div className="flex items-center gap-2 text-[11px]">
        <MarketTabs value={market} onChange={onMarketChange} />
        <div className="inline-flex rounded-md border border-border bg-panel-2 p-0.5">
          {DATA_SOURCE_MODES.map((mode) => (
            <button
              key={mode}
              type="button"
              onClick={() => onSourceModeChange(mode)}
              className={`rounded px-2 py-0.5 text-[10px] transition-colors ${
                sourceMode === mode ? 'bg-accent/15 text-fg' : 'text-muted hover:text-fg'
              }`}
            >
              {mode === 'auto' ? 'AUTO' : mode === 'eastmoney' ? '东方' : mode.toUpperCase()}
            </button>
          ))}
        </div>
        {editing ? (
          <>
            <button
              type="button"
              onClick={onSaveLayout}
              className="chip text-up !border-up/40 hover:!bg-up/10 px-2.5 py-1"
            >
              SAVE
            </button>
            <button
              type="button"
              onClick={onResetLayout}
              className="chip text-muted hover:text-fg px-2.5 py-1"
            >
              RESET
            </button>
          </>
        ) : (
          <button
            type="button"
            onClick={onToggleEdit}
            className="chip text-muted hover:text-fg px-2.5 py-1"
          >
            EDIT LAYOUT
          </button>
        )}
        <button
          type="button"
          onClick={onOpenSources}
          className="chip text-muted hover:text-fg px-2.5 py-1"
        >
          DATA SOURCES
        </button>
        <span className="flex items-center gap-1.5 rounded-md border border-up/30 bg-up/5 text-up px-2.5 py-1">
          <span className="relative flex h-1.5 w-1.5">
            <span className="absolute inline-flex h-full w-full rounded-full bg-up opacity-60 animate-ping" />
            <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-up" />
          </span>
          LIVE
        </span>
        <span className="tab-nums text-fg-dim border border-border rounded-md px-2.5 py-1">
          {clock}<span className="text-muted ml-1">UTC</span>
        </span>
      </div>
    </header>
  );
}
