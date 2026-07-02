import type { Ticker } from '@tradeck/shared';

/**
 * 已知指数 symbol（eastmoney 指数不带 ^ 前缀，需显式枚举）。
 * yahoo 指数均以 ^ 开头（^GSPC / ^IXIC / ^DJI），由 isIndex 的 startsWith('^') 覆盖。
 */
const EASTMONEY_INDEX_SYMBOLS = new Set([
  '1.000001',   // 上证指数
  '0.399001',   // 深证成指
  '0.399006',   // 创业板指
  '1.000688',   // 科创50
  '1.000300',   // 沪深300
  '1.000016',   // 上证50
  '1.000905',   // 中证500
  '100.HSI',    // 恒生指数
  '100.HSTECH', // 恒生科技
]);

/** 判断一个 ticker 是否是市场指数（而非个股）。 */
export function isIndex(t: Ticker): boolean {
  return t.symbol.startsWith('^') || EASTMONEY_INDEX_SYMBOLS.has(t.symbol);
}

/**
 * 规范化 symbol 用于去重：剥掉 eastmoney 的 `{market}.` 前缀。
 * 例：`105.AAPL` → `AAPL`，`1.600519` → `600519`，`^GSPC` → `^GSPC`。
 */
export function canonical(symbol: string): string {
  const idx = symbol.indexOf('.');
  // 只剥数字前缀（1./0./105./116./100.），不剥小数点（如 BTC-USD）
  if (idx > 0 && /^\d+$/.test(symbol.slice(0, idx))) {
    return symbol.slice(idx + 1);
  }
  return symbol;
}

/**
 * 去重：同一只股票可能在 eastmoney 和 yahoo 都有（如 105.AAPL 和 AAPL）。
 * 规范化后按 symbol 去重，优先保留 eastmoney 版（有 volume、market 对齐）。
 * 指数不去重（^GSPC 和 1.000001 规范化后不同，各自保留）。
 */
export function dedupeTickers(tickers: Ticker[]): Ticker[] {
  const map = new Map<string, Ticker>();
  for (const t of tickers) {
    const key = canonical(t.symbol);
    const prev = map.get(key);
    if (!prev) {
      map.set(key, t);
      continue;
    }
    // 优先 eastmoney（有 volume、对齐 market tab）
    if (t.source === 'eastmoney' && prev.source !== 'eastmoney') {
      map.set(key, t);
    }
  }
  return [...map.values()];
}

/** 从 tickers 中筛出指数。 */
export function getIndexTickers(tickers: Ticker[]): Ticker[] {
  return dedupeTickers(tickers).filter(isIndex);
}

/** 从 tickers 中筛出个股（非指数）。 */
export function getStockTickers(tickers: Ticker[]): Ticker[] {
  return dedupeTickers(tickers).filter((t) => !isIndex(t));
}
