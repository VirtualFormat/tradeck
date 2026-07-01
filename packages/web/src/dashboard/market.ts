import type { Ticker } from '@tradeck/shared';

export const MARKETS = ['cn', 'hk', 'us'] as const;
export type Market = (typeof MARKETS)[number];
export const DATA_SOURCE_MODES = ['auto', 'mock', 'eastmoney', 'futu'] as const;
export type DataSourceMode = (typeof DATA_SOURCE_MODES)[number];

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
export function filterByMarket(
  tickers: Ticker[] | undefined,
  market: Market,
  sourceMode: DataSourceMode = 'auto',
): Ticker[] {
  const list = tickers ?? [];
  if (sourceMode === 'mock') return list.filter((t) => t.source === 'mock');
  const live = list.filter(
    (t) => t.market === market && (sourceMode === 'auto' || t.source.startsWith(`${sourceMode}-`)),
  );
  if (live.length > 0) return live;
  return sourceMode === 'auto' ? list.filter((t) => t.source === 'mock') : [];
}
