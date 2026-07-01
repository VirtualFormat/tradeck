import type {
  CreateDataSourceDto,
  DashboardLayout,
  DataSource,
  DataSourceWithHealth,
  FeedItem,
  MarketDepthResponse,
  OHLCV,
  OhlcvInterval,
  Ticker,
  UpdateDataSourceDto,
} from '@tradeck/shared';

// 走 vite proxy（/api → wrangler 8787），部署后同域。serverless 不直连外部源。
export const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '';

async function jsonReq<T>(path: string, method: string, body?: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers: body ? { 'content-type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new Error(`${method} ${path} failed: ${res.status}`);
  return res.json() as Promise<T>;
}

export async function fetchOhlcv(
  symbol: string,
  interval: OhlcvInterval,
  limit = 500,
): Promise<OHLCV[]> {
  const url = `${API_BASE}/api/ohlcv?symbol=${symbol}&interval=${interval}&limit=${limit}`;
  const res = await fetch(url);
  if (!res.ok) throw new Error(`fetchOhlcv failed: ${res.status}`);
  return res.json() as Promise<OHLCV[]>;
}

export async function fetchTickers(): Promise<Ticker[]> {
  const res = await fetch(`${API_BASE}/api/tickers`);
  if (!res.ok) throw new Error(`fetchTickers failed: ${res.status}`);
  return res.json() as Promise<Ticker[]>;
}

export async function fetchMarketDepth(
  source: string,
  market: string,
): Promise<MarketDepthResponse> {
  const url = `${API_BASE}/api/market-depth?source=${encodeURIComponent(source)}&market=${encodeURIComponent(market)}`;
  const res = await fetch(url);
  if (!res.ok) throw new Error(`fetchMarketDepth failed: ${res.status}`);
  return res.json() as Promise<MarketDepthResponse>;
}

export async function fetchFeed(limit = 30): Promise<FeedItem[]> {
  const res = await fetch(`${API_BASE}/api/feed?limit=${limit}`);
  if (!res.ok) throw new Error(`fetchFeed failed: ${res.status}`);
  return res.json() as Promise<FeedItem[]>;
}

export const fetchDataSources = (): Promise<DataSourceWithHealth[]> =>
  jsonReq('/api/datasources', 'GET');

export const createDataSource = (dto: CreateDataSourceDto): Promise<DataSource> =>
  jsonReq('/api/datasources', 'POST', dto);

export const updateDataSource = (id: string, dto: UpdateDataSourceDto): Promise<DataSource> =>
  jsonReq(`/api/datasources/${id}`, 'PATCH', dto);

export const deleteDataSource = (id: string): Promise<{ ok: true }> =>
  jsonReq(`/api/datasources/${id}`, 'DELETE');

export const fetchLayout = (): Promise<DashboardLayout> =>
  jsonReq('/api/dashboard/layout', 'GET');

export const saveLayout = (layout: DashboardLayout): Promise<DashboardLayout> =>
  jsonReq('/api/dashboard/layout', 'PUT', layout);
