import { Inject, Injectable } from '@nestjs/common';
import { and, desc, eq } from 'drizzle-orm';
import type Redis from 'ioredis';
import type { MarketTick, OHLCV, OhlcvInterval, Ticker } from '@tradeck/shared';
import { DRIZZLE, type Database } from '../../infra/db/db.types';
import { ohlcv } from '../../infra/db/schema';
import { REDIS_CLIENT } from '../../infra/redis/redis.tokens';

@Injectable()
export class MarketService {
  constructor(
    @Inject(DRIZZLE) private readonly db: Database,
    @Inject(REDIS_CLIENT) private readonly redis: Redis,
  ) {}

  async query(symbol: string, interval: OhlcvInterval, limit: number): Promise<OHLCV[]> {
    const rows = await this.db
      .select()
      .from(ohlcv)
      .where(and(eq(ohlcv.symbol, symbol), eq(ohlcv.interval, interval)))
      .orderBy(desc(ohlcv.ts))
      .limit(limit);
    // SQL returns newest-first; charts want oldest-first.
    return rows.reverse() as OHLCV[];
  }

  /**
   * All latest per-symbol snapshots (from Redis `latest:{source}:{symbol}`),
   * enriched with intraday change% from the current 1m candle (c-o)/o.
   * Drives the overview / movers / heatmap panels.
   */
  async listTickers(): Promise<Ticker[]> {
    const keys = await this.redis.keys('latest:*');
    if (keys.length === 0) return [];
    const raws = await this.redis.mget(keys);
    const tickers: Ticker[] = [];
    for (const raw of raws) {
      if (!raw) continue;
      let tick: MarketTick;
      try {
        tick = JSON.parse(raw) as MarketTick;
      } catch {
        continue;
      }
      const recent = await this.recentCloses(tick.symbol, 30);
      // intraday change from the current (newest) 1m candle's open vs live price
      const open = recent.opens.at(-1);
      const changePct = open && open !== 0 ? (tick.price - open) / open : 0;
      // sparkline = recent closes oldest→newest, with the live price as the tip
      const spark = recent.closes.length > 0 ? [...recent.closes, tick.price] : [];
      tickers.push({
        source: tick.source,
        symbol: tick.symbol,
        price: tick.price,
        volume: tick.volume,
        ts: tick.ts,
        changePct,
        spark,
      });
    }
    return tickers.sort((a, b) => b.changePct - a.changePct);
  }

  /** Recent 1m candles (oldest→newest) as parallel opens/closes arrays. */
  private async recentCloses(
    symbol: string,
    limit: number,
  ): Promise<{ opens: number[]; closes: number[] }> {
    const rows = await this.db
      .select()
      .from(ohlcv)
      .where(and(eq(ohlcv.symbol, symbol), eq(ohlcv.interval, '1m')))
      .orderBy(desc(ohlcv.ts))
      .limit(limit);
    rows.reverse(); // newest-first → oldest-first
    return { opens: rows.map((r) => r.o), closes: rows.map((r) => r.c) };
  }
}
