import { z } from 'zod';

/**
 * Fallback model for custom HTTP sources (http-json connector + JSONPath
 * mapping). Any value that does not fit MarketTick/OHLCV/FeedItem lands here.
 */
export const GenericMetricSchema = z.object({
  source: z.string().min(1),
  /** Metric key (e.g. "open_interest", "funding_rate"). */
  key: z.string().min(1),
  /** Observation timestamp, epoch milliseconds. */
  ts: z.number().int().nonnegative(),
  value: z.number(),
  /** Arbitrary source-specific metadata. */
  meta: z.record(z.string(), z.unknown()).optional(),
});

export type GenericMetric = z.infer<typeof GenericMetricSchema>;
