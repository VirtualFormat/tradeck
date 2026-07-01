import type { MarketTick, OHLCV } from '@tradeck/shared';

/**
 * Yahoo Finance 连接器（Pull 型）。
 * 注意：非官方端点，可能变动；全部封装在这一处便于维护。
 * 在 Worker（服务端）调用，规避浏览器 CORS。
 */

const QUOTE_ENDPOINT = 'https://query1.finance.yahoo.com/v7/finance/quote';
const CHART_ENDPOINT = 'https://query1.finance.yahoo.com/v8/finance/chart';

const UA =
  'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36';

interface YahooQuoteRaw {
  symbol: string;
  regularMarketPrice?: number;
  regularMarketChange?: number;
  regularMarketChangePercent?: number;
  regularMarketVolume?: number;
  regularMarketTime?: number; // epoch seconds
  shortName?: string;
  longName?: string;
  currency?: string;
}

/** 批量拉最新报价并归一化为 MarketTick[] */
export async function fetchQuotes(symbols: string[]): Promise<MarketTick[]> {
  if (symbols.length === 0) return [];
  const url = `${QUOTE_ENDPOINT}?symbols=${encodeURIComponent(symbols.join(','))}`;
  const res = await fetch(url, {
    headers: { 'User-Agent': UA, Accept: 'application/json' },
  });
  if (!res.ok) {
    throw new Error(`Yahoo quote HTTP ${res.status}`);
  }
  const json = (await res.json()) as { quoteResponse?: { result?: YahooQuoteRaw[] } };
  const rows = json.quoteResponse?.result ?? [];
  return rows.map(normalizeQuote);
}

function normalizeQuote(r: YahooQuoteRaw): MarketTick {
  return {
    source: 'yahoo',
    symbol: r.symbol,
    ts: (r.regularMarketTime ?? Math.floor(Date.now() / 1000)) * 1000,
    price: r.regularMarketPrice ?? 0,
    change: r.regularMarketChange,
    changePercent: r.regularMarketChangePercent,
    volume: r.regularMarketVolume,
    name: r.shortName ?? r.longName,
    currency: r.currency,
  };
}

/** 拉历史 K 线并归一化为 OHLCV[]（历史面板用） */
export async function fetchChart(
  symbol: string,
  range = '1mo',
  interval = '1d',
): Promise<OHLCV[]> {
  const url = `${CHART_ENDPOINT}/${encodeURIComponent(symbol)}?range=${range}&interval=${interval}`;
  const res = await fetch(url, {
    headers: { 'User-Agent': UA, Accept: 'application/json' },
  });
  if (!res.ok) throw new Error(`Yahoo chart HTTP ${res.status}`);
  const json = (await res.json()) as {
    chart?: {
      result?: {
        timestamp?: number[];
        indicators?: { quote?: { open?: number[]; high?: number[]; low?: number[]; close?: number[]; volume?: number[] }[] };
      }[];
    };
  };
  const result = json.chart?.result?.[0];
  const ts = result?.timestamp ?? [];
  const q = result?.indicators?.quote?.[0];
  if (!q) return [];
  const out: OHLCV[] = [];
  for (let i = 0; i < ts.length; i++) {
    if (q.open?.[i] == null || q.close?.[i] == null) continue;
    out.push({
      source: 'yahoo',
      symbol,
      interval,
      ts: ts[i] * 1000,
      o: q.open[i]!,
      h: q.high?.[i] ?? q.open[i]!,
      l: q.low?.[i] ?? q.open[i]!,
      c: q.close[i]!,
      v: q.volume?.[i],
    });
  }
  return out;
}
