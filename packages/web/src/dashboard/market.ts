import type { Ticker } from '@tradeck/shared';

export const MARKETS = ['cn', 'hk', 'us'] as const;
export type Market = (typeof MARKETS)[number];

// 保留 mock/futu 保持类型兼容（旧组件有比较分支），但 UI 只显示 auto/eastmoney。
export const DATA_SOURCE_MODES = ['auto', 'eastmoney', 'mock', 'futu'] as const;
export type DataSourceMode = (typeof DATA_SOURCE_MODES)[number];

// UI 上只显示这两个模式（生产环境无 mock/futu 数据源）。
export const VISIBLE_SOURCE_MODES: DataSourceMode[] = ['auto', 'eastmoney'];

export const MARKET_LABEL: Record<Market, string> = {
  cn: 'A股',
  hk: '港股',
  us: '美股',
};

/**
 * Tickers for a market tab.
 * - auto: 优先东方财富，无则用 yahoo（美股/指数/加密）
 * - eastmoney: 只看东方财富
 * - mock/futu: 保留兼容（生产环境无此数据源，返回空）
 */
export function filterByMarket(
  tickers: Ticker[] | undefined,
  market: Market,
  sourceMode: DataSourceMode = 'auto',
): Ticker[] {
  const list = tickers ?? [];
  if (sourceMode === 'mock') return list.filter((t) => t.source === 'mock');
  if (sourceMode === 'futu') return list.filter((t) => t.source.startsWith('futu'));
  if (sourceMode === 'eastmoney') {
    return list.filter((t) => t.source === 'eastmoney' && t.market === market);
  }
  // auto: 优先该市场的东方财富，无则用 yahoo
  const live = list.filter((t) => t.market === market && t.source === 'eastmoney');
  if (live.length > 0) return live;
  if (market === 'us') {
    const yh = list.filter((t) => t.source === 'yahoo');
    if (yh.length > 0) return yh;
  }
  return [];
}
