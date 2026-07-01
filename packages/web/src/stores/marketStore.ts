import { create } from 'zustand';
import type { MarketTick, OHLCV } from '@tradeck/shared';

interface MarketState {
  lastTickBySymbol: Record<string, MarketTick | undefined>;
  /** Latest (in-progress / last) candle pushed via SSE, per symbol. */
  liveCandleBySymbol: Record<string, OHLCV | undefined>;
  applyCandle: (candle: OHLCV) => void;
}

/** Real-time stream state only (Zustand). Requested data lives in TanStack Query. */
export const useMarketStore = create<MarketState>((set) => ({
  lastTickBySymbol: {},
  liveCandleBySymbol: {},
  applyCandle: (candle) =>
    set((s) => ({
      liveCandleBySymbol: { ...s.liveCandleBySymbol, [candle.symbol]: candle },
    })),
}));
