import { useQuery } from '@tanstack/react-query';
import type { OhlcvInterval } from '@tradeck/shared';
import { fetchOhlcv } from './http';

export function useOhlcv(symbol: string, interval: OhlcvInterval) {
  return useQuery({
    queryKey: ['ohlcv', symbol, interval],
    queryFn: () => fetchOhlcv(symbol, interval),
    staleTime: 60_000,
  });
}
