import { MARKET_LABEL, MARKETS, type Market } from '../market';

interface Props {
  value: Market;
  onChange: (m: Market) => void;
}

export function MarketTabs({ value, onChange }: Props): JSX.Element {
  return (
    <div className="inline-flex items-center gap-1 rounded-md border border-border bg-panel-2 p-0.5">
      {MARKETS.map((m) => (
        <button
          key={m}
          type="button"
          onClick={() => onChange(m)}
          className={`rounded px-3 py-1 text-[11px] transition-colors ${
            m === value
              ? 'bg-accent/15 text-fg'
              : 'text-muted hover:text-fg'
          }`}
        >
          {MARKET_LABEL[m]}
        </button>
      ))}
    </div>
  );
}
