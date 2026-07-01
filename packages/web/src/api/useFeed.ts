import { useQuery } from '@tanstack/react-query';
import { fetchFeed } from './http';

/** Polls the feed every 10s (requested data -> TanStack Query). */
export function useFeed(limit = 30) {
  return useQuery({
    queryKey: ['feed', limit],
    queryFn: () => fetchFeed(limit),
    refetchInterval: 10_000,
  });
}
