import type { Ticker } from '@tradeck/shared';

export const MARKETS = ['cn', 'hk', 'us'] as const;
export type Market = (typeof MARKETS)[number];

export const MARKET_LABEL: Record<Market, string> = {
  cn: 'A股',
  hk: '港股',
  us: '美股',
};

/**
 * Tickers for a market tab. Prefer the market's live (eastmoney) tickers;
 * if none are available (off-hours / source down / not yet ingested), fall
 * back to the mock source so the panels still show moving data.
 */
export function filterByMarket(tickers: Ticker[] | undefined, market: Market): Ticker[] {
  const list = tickers ?? [];
  const live = list.filter((t) => t.market === market);
  if (live.length > 0) return live;
  return list.filter((t) => t.source === 'mock');
}
