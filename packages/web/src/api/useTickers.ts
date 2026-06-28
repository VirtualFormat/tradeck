import { useQuery } from '@tanstack/react-query';
import { fetchTickers } from './http';

/** Polls all latest tickers every 3s (drives overview / movers / heatmap). */
export function useTickers() {
  return useQuery({ queryKey: ['tickers'], queryFn: fetchTickers, refetchInterval: 3000 });
}
