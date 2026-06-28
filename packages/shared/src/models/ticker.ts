import { z } from 'zod';

/** Latest snapshot of a symbol plus its intraday change %, for overview/rank/heatmap. */
export const TickerSchema = z.object({
  source: z.string(),
  symbol: z.string(),
  price: z.number(),
  volume: z.number().optional(),
  ts: z.number(),
  /** intraday change fraction, e.g. 0.0123 = +1.23% (from latest 1m candle (c-o)/o) */
  changePct: z.number(),
  /** recent close prices (oldest→newest) for a background sparkline; may be empty */
  spark: z.array(z.number()).default([]),
});
export type Ticker = z.infer<typeof TickerSchema>;
