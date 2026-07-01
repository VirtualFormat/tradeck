import { useQuery } from '@tanstack/react-query';
import { fetchMarketDepth } from './http';

export function useMarketDepth(source: string, market: string, enabled: boolean) {
  return useQuery({
    queryKey: ['market-depth', source, market],
    queryFn: () => fetchMarketDepth(source, market),
    enabled,
    refetchInterval: enabled ? 10000 : false,
  });
}
