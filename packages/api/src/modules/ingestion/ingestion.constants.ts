/** Redis key holding the latest tick snapshot for a source+symbol. */
export const snapshotKey = (source: string, symbol: string): string =>
  `latest:${source}:${symbol}`;

/** Redis pub/sub channel carrying OHLCV candle updates for fan-out to SSE. */
export const candleChannel = (symbol: string, interval: string): string =>
  `candle:${symbol}:${interval}`;

/** Redis pub/sub channel announcing new feed items. */
export const FEED_CHANNEL = 'feed:new';
