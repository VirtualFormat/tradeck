import type { Ticker } from '@tradeck/shared';

/**
 * 东方财富连接器（Pull 型，serverless 版）。
 * 端点 push2.eastmoney.com 在容器内可达（ unlike Yahoo 被封 ）。
 * 一次批量请求拉所有 secids 的最新报价，归一化为 Ticker[]。
 *
 * secid 格式：{market}.{code}
 *   1.=SH  0.=SZ  116.=HK  100.=HSI  105/106/107.=US
 */

const UA =
  'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36';

// 固定关注列表（MVP 阶段无个性化配置）
const SECIDS: { secid: string; market: 'cn' | 'hk' | 'us' }[] = [
  // A股大盘指数
  { secid: '1.000001', market: 'cn' },   // 上证指数
  { secid: '0.399001', market: 'cn' },   // 深证成指
  { secid: '0.399006', market: 'cn' },   // 创业板指
  { secid: '1.000688', market: 'cn' },   // 科创50
  { secid: '1.000300', market: 'cn' },   // 沪深300
  { secid: '1.000016', market: 'cn' },   // 上证50
  { secid: '1.000905', market: 'cn' },   // 中证500
  // A股个股（MoversBar 用）
  { secid: '1.600519', market: 'cn' },
  { secid: '0.300750', market: 'cn' },
  { secid: '0.000858', market: 'cn' },
  { secid: '1.601318', market: 'cn' },
  // 港股指数
  { secid: '100.HSI', market: 'hk' },     // 恒生指数
  { secid: '100.HSTECH', market: 'hk' },  // 恒生科技
  // 港股个股
  { secid: '116.00700', market: 'hk' },
  { secid: '116.09988', market: 'hk' },
  { secid: '116.03690', market: 'hk' },
  // 美股
  { secid: '105.AAPL', market: 'us' },
  { secid: '105.TSLA', market: 'us' },
  { secid: '105.NVDA', market: 'us' },
  { secid: '105.MSFT', market: 'us' },
  { secid: '105.AMZN', market: 'us' },
];

interface EastmoneyRow {
  f2?: number | string;  // last price
  f3?: number | string;  // day change %
  f4?: number | string;  // 涨跌额
  f5?: number | string;  // volume (手)
  f6?: number | string;  // 成交额
  f7?: number | string;  // 振幅 %
  f12?: string;          // code
  f13?: number;          // market prefix
  f14?: string;          // name
  f15?: number | string; // 最高
  f16?: number | string; // 最低
  f17?: number | string; // 今开
  f18?: number | string; // 昨收
}

interface EastmoneyResponse {
  data?: { diff?: EastmoneyRow[] } | null;
}

/** 拉东方财富批量报价并归一化为 Ticker[] */
export async function fetchEastmoneyTickers(): Promise<Ticker[]> {
  const secids = SECIDS.map((s) => s.secid).join(',');
  // push2.eastmoney.com 在容器/数据中心 IP 上常被限流 502；push2delay（行情延迟版）可达。
  const url =
    'https://push2delay.eastmoney.com/api/qt/ulist.np/get' +
    `?secids=${encodeURIComponent(secids)}` +
    '&fields=f2,f3,f4,f5,f6,f7,f12,f13,f14,f15,f16,f17,f18&fltt=2&invt=2';

  const res = await fetch(url, {
    headers: { Referer: 'https://quote.eastmoney.com/', 'User-Agent': UA },
    signal: AbortSignal.timeout(8000),
  });
  if (!res.ok) throw new Error(`eastmoney http ${res.status}`);
  const json = (await res.json()) as EastmoneyResponse;
  const rows = json?.data?.diff;
  if (!Array.isArray(rows)) return [];

  const now = Date.now();
  const marketBySecid = new Map(SECIDS.map((s) => [s.secid, s.market]));
  const out: Ticker[] = [];

  for (const row of rows) {
    const price = typeof row.f2 === 'number' && row.f2 > 0 ? row.f2 : null;
    if (price === null || typeof row.f12 !== 'string' || row.f13 === undefined) continue;
    const secid = `${row.f13}.${row.f12}`;
    const changePct = typeof row.f3 === 'number' ? row.f3 / 100 : 0;
    const num = (v: number | string | undefined): number | undefined =>
      typeof v === 'number' ? v : typeof v === 'string' && v !== '' ? Number(v) : undefined;
    const change = num(row.f4);
    const amount = num(row.f6);
    const amplitude = typeof row.f7 === 'number' ? row.f7 / 100 : undefined;
    const high = num(row.f15);
    const low = num(row.f16);
    const open = num(row.f17);
    const prevClose = num(row.f18);
    out.push({
      source: 'eastmoney',
      symbol: secid,
      price,
      volume: typeof row.f5 === 'number' && row.f5 >= 0 ? row.f5 : undefined,
      ts: now,
      changePct,
      spark: [price * (1 - changePct), price], // 简化 sparkline（2 点）
      name: typeof row.f14 === 'string' ? row.f14 : undefined,
      market: marketBySecid.get(secid),
      change,
      amount,
      amplitude,
      high,
      low,
      open,
      prevClose,
    });
  }
  return out;
}
