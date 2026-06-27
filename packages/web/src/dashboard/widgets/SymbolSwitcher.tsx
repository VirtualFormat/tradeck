interface Props {
  symbols: string[];
  value: string;
  onChange: (s: string) => void;
}

export function SymbolSwitcher({ symbols, value, onChange }: Props): JSX.Element {
  return (
    <div className="flex items-center gap-1">
      {symbols.map((s) => (
        <button
          key={s}
          type="button"
          onClick={() => onChange(s)}
          className={`text-[11px] px-2 py-1 rounded border transition-colors ${
            s === value
              ? 'border-accent text-fg bg-panel-2'
              : 'border-border text-muted hover:text-fg'
          }`}
        >
          {s}
        </button>
      ))}
      <span className="text-muted text-[11px] ml-2 border border-border rounded px-2 py-1 opacity-60">
        1m
      </span>
    </div>
  );
}
