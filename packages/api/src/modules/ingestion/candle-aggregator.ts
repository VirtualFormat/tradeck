import type { MarketTick, OHLCV } from '@tradeck/shared';

const ONE_MINUTE_MS = 60_000;

/**
 * In-memory 1m candle aggregator (one bucket per source+symbol). Throttles
 * high-frequency ticks into candles: ticks within the same minute accumulate
 * into the current bucket; crossing a minute boundary flushes the previous
 * bucket as "closed" and opens a new one.
 *
 * State is process-local: on restart the in-progress bucket is lost, but
 * already-persisted candles are not (single-process MVP, acceptable).
 */
export class CandleAggregator {
  private readonly buckets = new Map<string, OHLCV>();

  add(tick: MarketTick): { current: OHLCV; closed: OHLCV | null } {
    const key = `${tick.source}:${tick.symbol}:1m`;
    const bucketTs = Math.floor(tick.ts / ONE_MINUTE_MS) * ONE_MINUTE_MS;
    const existing = this.buckets.get(key);

    if (!existing || existing.ts !== bucketTs) {
      const closed = existing ?? null;
      const current: OHLCV = {
        source: tick.source,
        symbol: tick.symbol,
        interval: '1m',
        ts: bucketTs,
        o: tick.price,
        h: tick.price,
        l: tick.price,
        c: tick.price,
        v: tick.volume ?? 0,
      };
      this.buckets.set(key, current);
      return { current, closed };
    }

    existing.h = Math.max(existing.h, tick.price);
    existing.l = Math.min(existing.l, tick.price);
    existing.c = tick.price;
    existing.v += tick.volume ?? 0;
    return { current: existing, closed: null };
  }
}
