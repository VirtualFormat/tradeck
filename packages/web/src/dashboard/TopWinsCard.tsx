import { Card } from './widgets/Card';
import { CandleChart } from '../charts/CandleChart';
import { LIVE_SYMBOL, topWinMock } from './mock/dashboardData';

export function TopWinsCard(): JSX.Element {
  const t = topWinMock;
  return (
    <Card title={`Live · ${LIVE_SYMBOL} · 1m`} corner="● live">
      <div className="flex items-end justify-between mb-2">
        <div className="tab-nums text-fg" style={{ fontSize: '2.5rem', lineHeight: 1 }}>
          ×{t.multiple.toFixed(2)}
        </div>
        <div className="text-right text-xs text-muted">
          <div>
            entry <span className="tab-nums text-fg">${t.entry.toLocaleString('en-US')}</span>
          </div>
          <div>
            payout{' '}
            <span className="tab-nums text-up">${t.payout.toLocaleString('en-US')}</span>
          </div>
        </div>
      </div>
      <CandleChart symbol={LIVE_SYMBOL} interval="1m" />
    </Card>
  );
}
