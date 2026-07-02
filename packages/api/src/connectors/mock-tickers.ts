import type { Ticker } from '@tradeck/shared';

/**
 * Mock tickers（兜底/开发）。东方财富拉取失败或需要 mock 源时使用。
 * 包含前端 DashboardPage 期望的 MOCKUSDT/MOCKETH/MOCKSOL（LIVE_SYMBOL）。
 * 另含 12 只大盘指数 mock 样本（A 股大盘 7 + 港股 2 + 美股 3），Yahoo 被封时兜底。
 */

interface MockDef {
  symbol: string;
  name: string;
  market: 'cn' | 'hk' | 'us' | undefined;
  base: number;     // 昨收基准价
  digits: number;   // 价格小数位
  amountBase: number; // 成交额基准（亿）
}

const MOCK_DEFS: MockDef[] = [
  // 加密 mock（保留，LIVE_SYMBOL 依赖）
  { symbol: 'MOCKUSDT', name: 'Mock BTC', market: undefined, base: 65000, digits: 2, amountBase: 0 },
  { symbol: 'MOCKETH', name: 'Mock ETH', market: undefined, base: 3400, digits: 2, amountBase: 0 },
  { symbol: 'MOCKSOL', name: 'Mock SOL', market: undefined, base: 180, digits: 2, amountBase: 0 },
  // A 股个股
  { symbol: '1.600519', name: '贵州茅台(mock)', market: 'cn', base: 1700, digits: 2, amountBase: 30 },
  { symbol: '116.00700', name: '腾讯(mock)', market: 'hk', base: 380, digits: 2, amountBase: 80 },
  { symbol: '105.AAPL', name: 'Apple(mock)', market: 'us', base: 225, digits: 2, amountBase: 50 },
  // A 股大盘指数（eastmoney 真实失败时兜底）
  { symbol: '1.000001', name: '上证指数', market: 'cn', base: 3280, digits: 2, amountBase: 4200 },
  { symbol: '0.399001', name: '深证成指', market: 'cn', base: 10450, digits: 2, amountBase: 5100 },
  { symbol: '0.399006', name: '创业板指', market: 'cn', base: 2080, digits: 2, amountBase: 2200 },
  { symbol: '1.000688', name: '科创50', market: 'cn', base: 980, digits: 2, amountBase: 850 },
  { symbol: '1.000300', name: '沪深300', market: 'cn', base: 3850, digits: 2, amountBase: 3200 },
  { symbol: '1.000016', name: '上证50', market: 'cn', base: 2620, digits: 2, amountBase: 1100 },
  { symbol: '1.000905', name: '中证500', market: 'cn', base: 5180, digits: 2, amountBase: 1800 },
  // 港股指数
  { symbol: '100.HSI', name: '恒生指数', market: 'hk', base: 18200, digits: 2, amountBase: 1100 },
  { symbol: '100.HSTECH', name: '恒生科技', market: 'hk', base: 3850, digits: 2, amountBase: 480 },
  // 美股指数（Yahoo dev 失败兜底）
  { symbol: '^GSPC', name: '标普500', market: 'us', base: 5450, digits: 2, amountBase: 0 },
  { symbol: '^IXIC', name: '纳斯达克', market: 'us', base: 17600, digits: 2, amountBase: 0 },
  { symbol: '^DJI', name: '道琼斯', market: 'us', base: 39500, digits: 2, amountBase: 0 },
];

export function mockTickers(): Ticker[] {
  const now = Date.now();
  const seed = Math.floor(now / 3000); // 每 3 秒变一次
  return MOCK_DEFS.map((d) => {
    const r = pseudoRandom(d.symbol + seed);
    const changePct = (r - 0.5) * 0.08; // ±4%
    const price = Number((d.base * (1 + changePct)).toFixed(d.digits));
    const change = Number((price - d.base).toFixed(d.digits));
    const open = Number((d.base * (1 + (r - 0.5) * 0.01)).toFixed(d.digits));
    const high = Number(Math.max(price, open) * (1 + r * 0.005)).toFixed(d.digits);
    const low = Number(Math.min(price, open) * (1 - r * 0.005)).toFixed(d.digits);
    const amplitude = (Number(high) - Number(low)) / d.base;
    const amount = d.amountBase > 0 ? Math.round(d.amountBase * (0.7 + r * 0.6) * 1e8) : undefined;
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
      open,
      high: Number(high),
      low: Number(low),
      prevClose: d.base,
      change,
      amount,
      amplitude,
    } satisfies Ticker;
  });
}

function pseudoRandom(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
  return (h % 10000) / 10000;
}
