import type { OHLCV } from '@tradeck/shared';
import type { OhlcvInterval } from '@tradeck/shared';

/**
 * Mock OHLCV 生成（Yahoo 本地被封时兜底）。生成合成 K 线序列。
 * 部署到 Cloudflare 后可用 Yahoo chart 端点替代。
 */
const BASE_PRICE: Record<string, number> = {
  MOCKUSDT: 65000,
  MOCKETH: 3400,
  MOCKSOL: 180,
  '1.600519': 1700,
  '116.00700': 380,
  '105.AAPL': 225,
};

export function mockOhlcv(symbol: string, interval: OhlcvInterval, limit: number): OHLCV[] {
  const base = BASE_PRICE[symbol] ?? 100;
  const intervalMs: Record<OhlcvInterval, number> = {
    '1m': 60_000,
    '5m': 300_000,
    '15m': 900_000,
    '1h': 3_600_000,
    '4h': 14_400_000,
    '1d': 86_400_000,
  };
  const step = intervalMs[interval] ?? 60_000;
  const now = Date.now();
  const out: OHLCV[] = [];
  let prev = base;
  for (let i = limit - 1; i >= 0; i--) {
    const ts = now - i * step;
    const seed = symbol + ts;
    const r = pseudoRandom(seed);
    const change = (r - 0.5) * base * 0.02; // ±1% per candle
    const o = prev;
    const c = Number((o + change).toFixed(2));
    const h = Number(Math.max(o, c, o + Math.abs(change) * 1.5).toFixed(2));
    const l = Number(Math.min(o, c, o - Math.abs(change) * 1.5).toFixed(2));
    const v = Math.floor(r * 100_000);
    out.push({ source: 'mock', symbol, interval, ts, o, h, l, c, v });
    prev = c;
  }
  return out;
}

function pseudoRandom(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
  return (h % 10000) / 10000;
}
