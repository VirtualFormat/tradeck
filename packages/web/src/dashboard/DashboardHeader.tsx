import { useEffect, useState } from 'react';
import { footerMock } from './mock/dashboardData';

function utcClock(): string {
  const d = new Date();
  const p = (n: number) => String(n).padStart(2, '0');
  return `${p(d.getUTCHours())}:${p(d.getUTCMinutes())}:${p(d.getUTCSeconds())} UTC`;
}

interface HeaderProps {
  onOpenSources: () => void;
  editing: boolean;
  onToggleEdit: () => void;
  onSaveLayout: () => void;
  onResetLayout: () => void;
}

export function DashboardHeader({
  onOpenSources,
  editing,
  onToggleEdit,
  onSaveLayout,
  onResetLayout,
}: HeaderProps): JSX.Element {
  const [clock, setClock] = useState(utcClock());

  useEffect(() => {
    const t = setInterval(() => setClock(utcClock()), 1000);
    return () => clearInterval(t);
  }, []);

  return (
    <header className="flex items-center justify-between bg-panel border border-border rounded-card px-4 py-3">
      <div className="flex items-center gap-3">
        <div className="w-8 h-8 rounded-full border border-border flex items-center justify-center text-muted">
          ◎
        </div>
        <div>
          <div className="text-muted text-[10px] uppercase tracking-[0.25em]">
            Tradeck · live market deck
          </div>
          <div className="text-fg text-base tracking-widest">TRADECK · MIROFISH</div>
        </div>
      </div>
      <div className="flex items-center gap-3 text-[11px]">
        {editing ? (
          <>
            <button
              type="button"
              onClick={onSaveLayout}
              className="border border-up/40 text-up rounded px-2 py-1"
            >
              SAVE
            </button>
            <button
              type="button"
              onClick={onResetLayout}
              className="border border-border text-muted hover:text-fg rounded px-2 py-1"
            >
              RESET
            </button>
          </>
        ) : (
          <button
            type="button"
            onClick={onToggleEdit}
            className="border border-border text-muted hover:text-fg rounded px-2 py-1"
          >
            EDIT LAYOUT
          </button>
        )}
        <button
          type="button"
          onClick={onOpenSources}
          className="border border-border text-muted hover:text-fg rounded px-2 py-1"
        >
          DATA SOURCES
        </button>
        <span className="flex items-center gap-1.5 border border-up/40 text-up rounded px-2 py-1">
          <span className="w-1.5 h-1.5 rounded-full bg-up animate-pulse" />
          LIVE · MAINNET
        </span>
        <span className="border border-border text-muted rounded px-2 py-1">
          ROUND #{footerMock.round}
        </span>
        <span className="tab-nums text-fg">{clock}</span>
      </div>
    </header>
  );
}
