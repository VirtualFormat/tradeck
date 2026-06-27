import { CandleChart } from './charts/CandleChart';
import { useTickStream } from './api/useTickStream';

const SYMBOL = 'BTCUSDT';

export function App(): JSX.Element {
  useTickStream(SYMBOL);
  return (
    <main style={{ fontFamily: 'monospace', padding: 24, background: '#0b0e14', minHeight: '100vh', color: '#d1d4dc' }}>
      <h1>Tradeck</h1>
      <p>{SYMBOL} · 1m · live</p>
      <CandleChart symbol={SYMBOL} interval="1m" />
    </main>
  );
}
