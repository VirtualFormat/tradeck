import { Card } from './widgets/Card';
import { CandleChart } from '../charts/CandleChart';
import { SymbolSwitcher } from './widgets/SymbolSwitcher';
import { LIVE_SYMBOLS } from './mock/dashboardData';
import type { DataSourceMode } from './market';

interface Props {
  symbol: string;
  onSymbolChange: (s: string) => void;
  symbols?: string[];
  sourceMode: DataSourceMode;
}

export function TopWinsCard({ symbol, onSymbolChange, symbols, sourceMode }: Props): JSX.Element {
  const hasSourceSymbols = symbols && symbols.length > 0;
  const choices = hasSourceSymbols ? symbols : sourceMode === 'mock' ? [...LIVE_SYMBOLS] : [];
  const waiting = sourceMode !== 'mock' && !hasSourceSymbols;
  return (
    <Card
      title="实时K线"
      subtitle={waiting ? 'Price Chart · waiting for source' : `Price Chart · ${symbol} · 1m`}
      corner={choices.length > 0 ? <SymbolSwitcher symbols={choices} value={symbol} onChange={onSymbolChange} /> : null}
    >
      {waiting ? (
        <div className="flex h-full items-center justify-center text-xs text-muted">
          等待 {sourceMode === 'futu' ? 'Futu OpenD' : '行情源'} 数据
        </div>
      ) : (
        <CandleChart symbol={symbol} interval="1m" />
      )}
    </Card>
  );
}
