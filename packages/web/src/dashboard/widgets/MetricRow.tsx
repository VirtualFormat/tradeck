import type { MetricItem } from '../mock/dashboardData';

const toneClass: Record<NonNullable<MetricItem['tone']>, string> = {
  up: 'text-up',
  down: 'text-down',
  neutral: 'text-fg',
};

export function MetricRow({ label, value, tone }: MetricItem): JSX.Element {
  return (
    <div className="flex items-baseline justify-between py-1.5 border-b border-border/50 last:border-0">
      <span className="text-muted text-[10px] uppercase tracking-wider">{label}</span>
      <span className={`tab-nums text-sm ${toneClass[tone ?? 'neutral']}`}>{value}</span>
    </div>
  );
}
