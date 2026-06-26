import { OHLCV_INTERVALS, type MarketTick } from '@tradeck/shared';

// Smoke-test the shared contract: this compiles only if the workspace
// type import resolves correctly across packages.
const sample: MarketTick = {
  source: 'mock',
  symbol: 'BTCUSDT',
  ts: Date.now(),
  price: 0,
};

export function App(): JSX.Element {
  return (
    <main style={{ fontFamily: 'monospace', padding: 24 }}>
      <h1>Tradeck</h1>
      <p>scaffold up — shared contracts wired.</p>
      <p>sample tick source: {sample.source}</p>
      <p>ohlcv intervals: {OHLCV_INTERVALS.join(', ')}</p>
    </main>
  );
}
