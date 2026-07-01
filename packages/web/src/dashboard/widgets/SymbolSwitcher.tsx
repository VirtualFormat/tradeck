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
          className={`text-[10.5px] px-2 py-1 rounded-md border transition-colors ${
            s === value
              ? 'border-accent/60 text-fg bg-accent/10'
              : 'border-border text-muted hover:text-fg hover:border-border-strong'
          }`}
        >
          {s}
        </button>
      ))}
      <span className="text-muted text-[10.5px] ml-1.5 border border-border rounded-md px-2 py-1 opacity-70">
        1m
      </span>
    </div>
  );
}
