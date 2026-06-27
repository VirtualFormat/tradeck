import { Card } from './widgets/Card';
import { CandleChart } from '../charts/CandleChart';
import { SymbolSwitcher } from './widgets/SymbolSwitcher';
import { LIVE_SYMBOLS, topWinMock } from './mock/dashboardData';

interface Props {
  symbol: string;
  onSymbolChange: (s: string) => void;
}

export function TopWinsCard({ symbol, onSymbolChange }: Props): JSX.Element {
  const t = topWinMock;
  return (
    <Card
      title={`Live · ${symbol} · 1m`}
      corner={<SymbolSwitcher symbols={[...LIVE_SYMBOLS]} value={symbol} onChange={onSymbolChange} />}
    >
      <div className="flex items-end justify-between mb-2">
        <div className="tab-nums text-fg" style={{ fontSize: '2.5rem', lineHeight: 1 }}>
          ×{t.multiple.toFixed(2)}
        </div>
        <div className="text-right text-xs text-muted">
          <div>
            entry <span className="tab-nums text-fg">${t.entry.toLocaleString('en-US')}</span>
          </div>
          <div>
            payout <span className="tab-nums text-up">${t.payout.toLocaleString('en-US')}</span>
          </div>
        </div>
      </div>
      <CandleChart symbol={symbol} interval="1m" />
    </Card>
  );
}
