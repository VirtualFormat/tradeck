import { Inject, Injectable } from '@nestjs/common';
import { and, desc, eq } from 'drizzle-orm';
import type { OHLCV, OhlcvInterval } from '@tradeck/shared';
import { DRIZZLE, type Database } from '../../infra/db/db.types';
import { ohlcv } from '../../infra/db/schema';

@Injectable()
export class MarketService {
  constructor(@Inject(DRIZZLE) private readonly db: Database) {}

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
}
