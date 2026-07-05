/**
 * OpenBB Platform API 客户端
 * 后端地址通过环境变量配置（docker-compose 里 OPENBB_API_URL）
 */
const OPENBB_API_URL =
  process.env.OPENBB_API_URL ?? "http://localhost:6900";

const BASE = `${OPENBB_API_URL}/api/v1`;

export interface EquityQuote {
  symbol: string;
  name: string | null;
  last_price: number | null;
  change: number | null;
  change_percent: number | null;
  currency: string | null;
  volume: number | null;
  open: number | null;
  high: number | null;
  low: number | null;
  prev_close: number | null;
  exchange: string | null;
}

export interface HistoricalPrice {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

async function fetchJSON<T>(path: string, init?: RequestInit): Promise<T> {
  const url = `${BASE}${path}`;
  const res = await fetch(url, {
    ...init,
    headers: { Accept: "application/json", ...init?.headers },
  });
  if (!res.ok) {
    throw new Error(`OpenBB API ${path} failed: ${res.status}`);
  }
  // 某些 OpenBB 端点返回 200 但空 body，res.json() 会抛 "Unexpected end of JSON input"
  const text = await res.text();
  if (!text) {
    return { results: [] } as unknown as T;
  }
  try {
    return JSON.parse(text) as T;
  } catch {
    return { results: [] } as unknown as T;
  }
}

interface OpenBBResponse<T> {
  results: T[];
  warnings?: { message: string }[];
}

export async function getEquityQuote(
  symbol: string,
  provider: string = "yfinance"
): Promise<EquityQuote | null> {
  const data = await fetchJSON<OpenBBResponse<EquityQuote>>(
    `/equity/price/quote?provider=${provider}&symbol=${encodeURIComponent(symbol)}`
  );
  return data.results[0] ?? null;
}

export async function getEquityQuotes(
  symbols: string[],
  provider: string = "yfinance"
): Promise<EquityQuote[]> {
  const symbolStr = symbols.join(",");
  const data = await fetchJSON<OpenBBResponse<EquityQuote>>(
    `/equity/price/quote?provider=${provider}&symbol=${encodeURIComponent(symbolStr)}`
  );
  return data.results;
}

export async function getEquityHistorical(
  symbol: string,
  startDate: string,
  endDate: string,
  provider: string = "yfinance"
): Promise<HistoricalPrice[]> {
  const data = await fetchJSON<OpenBBResponse<HistoricalPrice>>(
    `/equity/price/historical?provider=${provider}&symbol=${encodeURIComponent(
      symbol
    )}&start_date=${startDate}&end_date=${endDate}`
  );
  return data.results;
}

export async function getIndexHistorical(
  symbol: string,
  startDate: string,
  endDate: string,
  provider: string = "yfinance"
): Promise<HistoricalPrice[]> {
  const data = await fetchJSON<OpenBBResponse<HistoricalPrice>>(
    `/index/price/historical?provider=${provider}&symbol=${encodeURIComponent(
      symbol
    )}&start_date=${startDate}&end_date=${endDate}`
  );
  return data.results;
}
