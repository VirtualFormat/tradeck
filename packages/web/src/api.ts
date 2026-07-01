import { useQuery } from '@tanstack/react-query';
import type { QuoteResponse, FeedResponse } from '@tradeck/shared';

/** 前端只 fetch 同源的自家 API（经 vite proxy → wrangler dev）；绝不直连 Yahoo/RSS。 */

async function getJson<T>(url: string): Promise<T> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${url} → HTTP ${res.status}`);
  return res.json() as Promise<T>;
}

/** 报价：定时轮询（refetchInterval）实现"准实时"刷新 */
export function useQuotes() {
  return useQuery({
    queryKey: ['quotes'],
    queryFn: () => getJson<QuoteResponse>('/api/quote'),
    refetchInterval: 15_000,
  });
}

/** 资讯流：低频轮询 */
export function useFeed() {
  return useQuery({
    queryKey: ['feed'],
    queryFn: () => getJson<FeedResponse>('/api/feed'),
    refetchInterval: 120_000,
  });
}
