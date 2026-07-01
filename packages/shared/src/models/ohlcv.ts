import { z } from 'zod';
import { OHLCV_INTERVALS } from '../constants.js';

/**
 * An aggregated candle (open/high/low/close/volume) for a symbol + interval.
 * Used for chart history (TanStack Query) and persisted in PG.
 */
export const OHLCVSchema = z.object({
  source: z.string().min(1),
  symbol: z.string().min(1),
  /** Candle interval. */
  interval: z.enum(OHLCV_INTERVALS),
  /** Candle open time, epoch milliseconds. */
  ts: z.number().int().nonnegative(),
  o: z.number(),
  h: z.number(),
  l: z.number(),
  c: z.number(),
  v: z.number().nonnegative(),
});

export type OHLCV = z.infer<typeof OHLCVSchema>;
