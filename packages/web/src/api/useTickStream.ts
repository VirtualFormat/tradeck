import { useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import type { OHLCV, Ticker } from '@tradeck/shared';
import { useMarketStore } from '../stores/marketStore';
import { fetchTickers } from './http';

/**
 * serverless 版：无常驻 SSE，改用 TanStack Query 轮询 /api/tickers。
 * 从结果中找到目标 symbol 的最新 tick，转成 OHLCV 形状喂给 Zustand
 * （TopWinsCard 等组件读 liveCandleBySymbol[symbol]）。
 */
export function useTickStream(symbol: string): void {
  const applyCandle = useMarketStore((s) => s.applyCandle);

  const { data } = useQuery({
    queryKey: ['tickers-stream', symbol],
    queryFn: fetchTickers,
    refetchInterval: 3000,
  });

  useEffect(() => {
    if (!data) return;
    const tick = data.find((t) => t.symbol === symbol);
    if (!tick) return;
    const candle = tickToCandle(tick);
    applyCandle(candle);
  }, [data, symbol, applyCandle]);
}

function tickToCandle(tick: Ticker): OHLCV {
  const price = tick.price;
  const open = tick.spark.length > 0 ? tick.spark[0] : price;
  const high = Math.max(open, price, ...tick.spark);
  const low = Math.min(open, price, ...tick.spark);
  return {
    source: tick.source,
    symbol: tick.symbol,
    interval: '1m',
    ts: tick.ts,
    o: open,
    h: high,
    l: low,
    c: price,
    v: tick.volume ?? 0,
  };
}
