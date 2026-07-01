interface Props {
  label: string;
  value: string;
}

export function StatPill({ label, value }: Props): JSX.Element {
  return (
    <div className="bg-panel-2 border border-border rounded px-2.5 py-1.5">
      <div className="text-muted text-[9px] uppercase tracking-wider">{label}</div>
      <div className="tab-nums text-fg text-sm mt-0.5">{value}</div>
    </div>
  );
}
