import { Card } from './widgets/Card';
import { CandleChart } from '../charts/CandleChart';
import { SymbolSwitcher } from './widgets/SymbolSwitcher';
import { LIVE_SYMBOLS } from './mock/dashboardData';

interface Props {
  symbol: string;
  onSymbolChange: (s: string) => void;
}

export function TopWinsCard({ symbol, onSymbolChange }: Props): JSX.Element {
  return (
    <Card
      title="实时K线"
      subtitle={`Price Chart · ${symbol} · 1m`}
      corner={<SymbolSwitcher symbols={[...LIVE_SYMBOLS]} value={symbol} onChange={onSymbolChange} />}
    >
      <CandleChart symbol={symbol} interval="1m" />
    </Card>
  );
}
