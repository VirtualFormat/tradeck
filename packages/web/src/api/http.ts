import type { OHLCV, OhlcvInterval } from '@tradeck/shared';

export const API_BASE = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:3000';

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
