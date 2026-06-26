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
});

export type MarketTick = z.infer<typeof MarketTickSchema>;
