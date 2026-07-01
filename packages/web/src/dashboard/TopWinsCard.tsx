import { Card } from './widgets/Card';
import { CandleChart } from '../charts/CandleChart';
import { SymbolSwitcher } from './widgets/SymbolSwitcher';
import { LIVE_SYMBOLS } from './mock/dashboardData';

interface Props {
  symbol: string;
  onSymbolChange: (s: string) => void;
  symbols?: string[];
}

export function TopWinsCard({ symbol, onSymbolChange, symbols }: Props): JSX.Element {
  const hasSourceSymbols = symbols && symbols.length > 0;
  // 无 tickers 时 fallback 到 mock symbols（保证 K 线图始终有内容）
  const choices = hasSourceSymbols ? symbols : [...LIVE_SYMBOLS];
  return (
    <Card
      title="实时K线"
      subtitle={`Price Chart · ${symbol} · 1m`}
      corner={choices.length > 0 ? <SymbolSwitcher symbols={choices} value={symbol} onChange={onSymbolChange} /> : null}
    >
      <CandleChart symbol={symbol} interval="1m" />
    </Card>
  );
}
