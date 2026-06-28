import { Card } from './widgets/Card';
import { DotMatrixNumber } from './widgets/DotMatrixNumber';
import { StatPill } from './widgets/StatPill';
import { pnlMock } from './mock/dashboardData';

export function PnlCard(): JSX.Element {
  const d = pnlMock;
  return (
    <Card title="累计盈亏" subtitle="PnL" demo corner="anon 0x06dc…4524">
      <DotMatrixNumber value={d.pnl} />
      <div className="grid grid-cols-4 gap-2 mt-4">
        <StatPill label="trades" value={d.trades.toLocaleString('en-US')} />
        <StatPill label="win rate" value={`${Math.round(d.winRate * 100)}%`} />
        <StatPill label="sharpe" value={d.sharpe.toFixed(2)} />
        <StatPill label="realized" value={`$${(d.realized / 1000).toFixed(0)}k`} />
      </div>
      <div className="mt-4 divide-y divide-border/50">
        {d.recentWins.map((w) => (
          <div key={w.symbol} className="flex items-center justify-between py-1.5 text-xs">
            <span className="text-muted">
              {w.symbol} · {w.label}
            </span>
            <span className="tab-nums text-up">+${w.amount.toLocaleString('en-US')}</span>
          </div>
        ))}
      </div>
    </Card>
  );
}
