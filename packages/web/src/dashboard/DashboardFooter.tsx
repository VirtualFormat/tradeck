import { footerMock } from './mock/dashboardData';

export function DashboardFooter(): JSX.Element {
  const f = footerMock;
  return (
    <footer className="flex flex-wrap items-center gap-x-6 gap-y-1 text-[11px] text-muted px-2 py-2">
      <span className="flex items-center gap-1.5">
        <span className="w-1.5 h-1.5 rounded-full bg-up" />
        系统在线 · online
      </span>
      <span>引擎 · {f.model}</span>
      <span className="tab-nums">{f.fills.toLocaleString('en-US')} fills</span>
      <span className="tab-nums">backtest · {f.backtest}</span>
      <span className="tab-nums">latency · {f.latencyMs}ms</span>
      <span className="ml-auto">stack · tradeck-core</span>
    </footer>
  );
}
