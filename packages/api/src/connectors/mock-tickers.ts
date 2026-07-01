import type { Ticker } from '@tradeck/shared';

/**
 * Mock tickers（兜底/开发）。东方财富拉取失败或需要 mock 源时使用。
 * 包含前端 DashboardPage 期望的 MOCKUSDT/MOCKETH/MOCKSOL（LIVE_SYMBOL）。
 */
const MOCK_DEFS: { symbol: string; name: string; market: 'cn' | 'hk' | 'us' | undefined; base: number }[] = [
  { symbol: 'MOCKUSDT', name: 'Mock BTC', market: undefined, base: 65000 },
  { symbol: 'MOCKETH', name: 'Mock ETH', market: undefined, base: 3400 },
  { symbol: 'MOCKSOL', name: 'Mock SOL', market: undefined, base: 180 },
  { symbol: '1.600519', name: '贵州茅台(mock)', market: 'cn', base: 1700 },
  { symbol: '116.00700', name: '腾讯(mock)', market: 'hk', base: 380 },
  { symbol: '105.AAPL', name: 'Apple(mock)', market: 'us', base: 225 },
];

export function mockTickers(): Ticker[] {
  const now = Date.now();
  const seed = Math.floor(now / 3000); // 每 3 秒变一次
  return MOCK_DEFS.map((d) => {
    const r = pseudoRandom(d.symbol + seed);
    const changePct = (r - 0.5) * 0.08; // ±4%
    const price = Number((d.base * (1 + changePct)).toFixed(2));
    return {
      source: 'mock',
      symbol: d.symbol,
      price,
      volume: Math.floor(r * 1_000_000),
      ts: now,
      changePct,
      spark: [d.base, price],
      name: d.name,
      market: d.market,
    };
  });
}

function pseudoRandom(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
  return (h % 10000) / 10000;
}
