import type { MarketTick } from '@tradeck/shared';
import { DEFAULT_WATCHLIST } from '@tradeck/shared';

/**
 * Mock 连接器（兜底/开发）。
 * Yahoo 拉取失败或断网时，仍能让前端跑通链路。
 */
export function mockQuotes(symbols: string[] = DEFAULT_WATCHLIST.map((w) => w.symbol)): MarketTick[] {
  const now = Date.now();
  return symbols.map((symbol) => {
    const base = seededPrice(symbol);
    const changePercent = (pseudoRandom(symbol + now.toString().slice(0, 8)) - 0.5) * 6;
    const change = (base * changePercent) / 100;
    const label = DEFAULT_WATCHLIST.find((w) => w.symbol === symbol)?.label;
    return {
      source: 'mock',
      symbol,
      ts: now,
      price: Number((base + change).toFixed(2)),
      change: Number(change.toFixed(2)),
      changePercent: Number(changePercent.toFixed(2)),
      volume: Math.floor(pseudoRandom(symbol) * 1_000_000),
      name: label,
      currency: 'USD',
    };
  });
}

function seededPrice(s: string): number {
  return 50 + pseudoRandom(s) * 950;
}

function pseudoRandom(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
  return (h % 10000) / 10000;
}
