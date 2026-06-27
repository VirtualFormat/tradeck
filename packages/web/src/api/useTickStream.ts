import { useEffect } from 'react';
import type { OHLCV } from '@tradeck/shared';
import { useMarketStore } from '../stores/marketStore';
import { API_BASE } from './http';

/** Opens an SSE connection for a symbol and feeds candle updates into Zustand. */
export function useTickStream(symbol: string): void {
  const applyCandle = useMarketStore((s) => s.applyCandle);

  useEffect(() => {
    const es = new EventSource(`${API_BASE}/api/stream?symbol=${symbol}`);
    es.onmessage = (e) => {
      try {
        applyCandle(JSON.parse(e.data) as OHLCV);
      } catch {
        /* ignore malformed events */
      }
    };
    // EventSource auto-reconnects on error; nothing to do here.
    return () => es.close();
  }, [symbol, applyCandle]);
}
