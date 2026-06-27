import { Inject, Injectable, Logger } from '@nestjs/common';
import type Redis from 'ioredis';
import {
  type FeedItem,
  type MarketTick,
  type NormalizedEvent,
  NormalizedEventSchema,
  type OHLCV,
} from '@tradeck/shared';
import { DRIZZLE, type Database } from '../../infra/db/db.types';
import { feedItems, ohlcv } from '../../infra/db/schema';
import { REDIS_CLIENT } from '../../infra/redis/redis.tokens';
import { CandleAggregator } from './candle-aggregator';
import { candleChannel, FEED_CHANNEL, snapshotKey } from './ingestion.constants';

/**
 * The single entry point for normalized data. Per architecture §3:
 * validate -> Redis snapshot -> throttled aggregate + persist to PG ->
 * Redis PUBLISH for fan-out. Failures are caught and logged so a single bad
 * event cannot crash the connector's timer (collection isolation).
 */
@Injectable()
export class IngestionService {
  private readonly logger = new Logger(IngestionService.name);
  private readonly aggregator = new CandleAggregator();

  constructor(
    @Inject(REDIS_CLIENT) private readonly redis: Redis,
    @Inject(DRIZZLE) private readonly db: Database,
  ) {}

  async ingest(evt: NormalizedEvent): Promise<void> {
    try {
      const parsed = NormalizedEventSchema.parse(evt);
      if (parsed.kind === 'tick') {
        await this.ingestTick(parsed.payload);
      } else if (parsed.kind === 'feed') {
        await this.ingestFeed(parsed.payload);
      }
      // ohlcv/metric kinds: not handled this round
    } catch (err) {
      this.logger.error('ingest failed', err);
    }
  }

  private async ingestTick(tick: MarketTick): Promise<void> {
    await this.redis.set(snapshotKey(tick.source, tick.symbol), JSON.stringify(tick));
    const { current, closed } = this.aggregator.add(tick);
    if (closed) await this.upsertCandle(closed);
    await this.upsertCandle(current);
    await this.redis.publish(candleChannel(tick.symbol, '1m'), JSON.stringify(current));
  }

  private async ingestFeed(item: FeedItem): Promise<void> {
    await this.db
      .insert(feedItems)
      .values({
        source: item.source,
        externalId: item.id,
        title: item.title,
        url: item.url,
        summary: item.summary ?? null,
        publishedAt: item.publishedAt,
        tags: item.tags ? JSON.stringify(item.tags) : null,
      })
      .onConflictDoNothing({ target: [feedItems.source, feedItems.externalId] });
    await this.redis.publish(FEED_CHANNEL, JSON.stringify(item));
  }

  private async upsertCandle(candle: OHLCV): Promise<void> {
    await this.db
      .insert(ohlcv)
      .values(candle)
      .onConflictDoUpdate({
        target: [ohlcv.source, ohlcv.symbol, ohlcv.interval, ohlcv.ts],
        set: { h: candle.h, l: candle.l, c: candle.c, v: candle.v },
      });
  }
}
