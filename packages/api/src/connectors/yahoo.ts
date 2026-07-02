import type { MarketTick, OHLCV } from '@tradeck/shared';

/**
 * Yahoo Finance 连接器（Pull 型）。
 * 注意：非官方端点，可能变动；全部封装在这一处便于维护。
 * 在 Worker（服务端）调用，规避浏览器 CORS。
 *
 * 重要：v7 quote 端点已被 Yahoo 封禁（429 Too Many Requests），
 * 改用 v8 chart 端点批量拉取，从 meta 提取最新报价。
 */

const CHART_ENDPOINT = 'https://query1.finance.yahoo.com/v8/finance/chart';

const UA =
  'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36';

interface ChartMeta {
  symbol?: string;
  regularMarketPrice?: number;
  chartPreviousClose?: number;
  previousClose?: number;
  regularMarketVolume?: number;
  regularMarketTime?: number;
  shortName?: string;
  longName?: string;
  currency?: string;
}

interface ChartResponse {
  chart?: { result?: { meta?: ChartMeta }[]; error?: { description?: string } };
}

/**
 * 批量拉最新报价并归一化为 MarketTick[]。
 * 用 v8 chart 端点逐个拉取（v7 批量 quote 已被 Yahoo 封禁 429）。
 * 并发拉取，单个失败不影响其他。
 */
export async function fetchQuotes(symbols: string[]): Promise<MarketTick[]> {
  if (symbols.length === 0) return [];
  const results = await Promise.allSettled(
    symbols.map((s) => fetchQuoteViaChart(s)),
  );
  return results
    .filter((r): r is PromiseFulfilledResult<MarketTick> => r.status === 'fulfilled')
    .map((r) => r.value);
}

/** 通过 v8 chart 端点拉单个 symbol 的最新报价 */
async function fetchQuoteViaChart(symbol: string): Promise<MarketTick> {
  const url = `${CHART_ENDPOINT}/${encodeURIComponent(symbol)}?range=1d&interval=1d`;
  const res = await fetch(url, {
    headers: { 'User-Agent': UA, Accept: 'application/json' },
    signal: AbortSignal.timeout(8000),
  });
  if (!res.ok) throw new Error(`Yahoo chart ${symbol} HTTP ${res.status}`);
  const json = (await res.json()) as ChartResponse;
  const meta = json.chart?.result?.[0]?.meta;
  if (!meta || meta.regularMarketPrice == null) {
    throw new Error(`Yahoo chart ${symbol}: no meta`);
  }
  const prevClose = meta.chartPreviousClose ?? meta.previousClose ?? meta.regularMarketPrice;
  const changePct = prevClose > 0 ? (meta.regularMarketPrice - prevClose) / prevClose : 0;
  return {
    source: 'yahoo',
    symbol: meta.symbol ?? symbol,
    ts: (meta.regularMarketTime ?? Math.floor(Date.now() / 1000)) * 1000,
    price: meta.regularMarketPrice,
    changePct,
    volume: meta.regularMarketVolume,
    name: meta.shortName ?? meta.longName,
    prevClose,
    change: meta.regularMarketPrice - prevClose,
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
      interval: interval as OHLCV['interval'],
      ts: ts[i] * 1000,
      o: q.open[i]!,
      h: q.high?.[i] ?? q.open[i]!,
      l: q.low?.[i] ?? q.open[i]!,
      c: q.close[i]!,
      v: q.volume?.[i] ?? 0,
    });
  }
  return out;
}
