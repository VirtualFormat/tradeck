import { z } from 'zod';
import { MarketTickSchema } from './market-tick.js';
import { OHLCVSchema } from './ohlcv.js';
import { FeedItemSchema } from './feed-item.js';
import { GenericMetricSchema } from './generic-metric.js';

/**
 * The single exit type of every Connector's `normalize()`. A discriminated
 * union (by `kind`) wrapping one of the four standard models. The Ingestion
 * pipeline consumes this and nothing else.
 */
export const NormalizedEventSchema = z.discriminatedUnion('kind', [
  z.object({ kind: z.literal('tick'), payload: MarketTickSchema }),
  z.object({ kind: z.literal('ohlcv'), payload: OHLCVSchema }),
  z.object({ kind: z.literal('feed'), payload: FeedItemSchema }),
  z.object({ kind: z.literal('metric'), payload: GenericMetricSchema }),
]);

export type NormalizedEvent = z.infer<typeof NormalizedEventSchema>;
