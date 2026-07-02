import { z } from 'zod';

/**
 * A single point-in-time price observation for a symbol.
 * Output of Push-type connectors (e.g. exchange WebSocket trade/ticker streams).
 */
export const MarketTickSchema = z.object({
  /** Connector instance / source id (e.g. "binance-ws"). */
  source: z.string().min(1),
  /** Instrument symbol, source-native (e.g. "BTCUSDT"). */
  symbol: z.string().min(1),
  /** Event timestamp, epoch milliseconds. */
  ts: z.number().int().nonnegative(),
  /** Last/trade price. */
  price: z.number(),
  /** Trade or rolling volume, when the source provides it. */
  volume: z.number().nonnegative().optional(),
  /** Day's change fraction (e.g. 0.0123 = +1.23%) when the source reports it
   * directly (e.g. stock quotes). Carried into the snapshot so overview/movers
   * can show real daily change instead of a recomputed intraminute delta.
   */
  changePct: z.number().optional(),
  /** 昨日收盘价（Yahoo chart meta 提供 chartPreviousClose） */
  prevClose: z.number().optional(),
  /** 绝对涨跌额（price - prevClose） */
  change: z.number().optional(),
  /** Human-friendly display name (e.g. "贵州茅台", "Apple"), source-provided. */
  name: z.string().optional(),
});

export type MarketTick = z.infer<typeof MarketTickSchema>;
