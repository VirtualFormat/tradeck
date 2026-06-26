/**
 * Public constants shared across web/api. Kept dependency-free so both the
 * frontend bundle and the NestJS backend can import without side effects.
 */

/** Supported OHLCV candle intervals. */
export const OHLCV_INTERVALS = [
  '1m',
  '5m',
  '15m',
  '1h',
  '4h',
  '1d',
] as const;

export type OhlcvInterval = (typeof OHLCV_INTERVALS)[number];

/**
 * Discriminator for the normalized event union produced by every Connector's
 * `normalize()`. One value per standard model in `models/`.
 */
export const NORMALIZED_KINDS = [
  'tick',
  'ohlcv',
  'feed',
  'metric',
] as const;

export type NormalizedKind = (typeof NORMALIZED_KINDS)[number];
