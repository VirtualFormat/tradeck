import { pgTable, text, doublePrecision, bigint, uniqueIndex } from 'drizzle-orm/pg-core';

/**
 * OHLCV candle history. One row per (source, symbol, interval, bucket-start).
 * High-frequency ticks are throttled into these rows by the ingestion
 * pipeline (the in-progress bucket is upserted, not appended), so a minute of
 * ticks occupies a single row instead of thousands.
 */
export const ohlcv = pgTable(
  'ohlcv',
  {
    source: text('source').notNull(),
    symbol: text('symbol').notNull(),
    interval: text('interval').notNull(),
    // bucket start time, epoch milliseconds
    ts: bigint('ts', { mode: 'number' }).notNull(),
    o: doublePrecision('o').notNull(),
    h: doublePrecision('h').notNull(),
    l: doublePrecision('l').notNull(),
    c: doublePrecision('c').notNull(),
    v: doublePrecision('v').notNull(),
  },
  (t) => ({
    uq: uniqueIndex('ohlcv_src_sym_int_ts_uq').on(t.source, t.symbol, t.interval, t.ts),
  }),
);

/**
 * Aggregated feed (news / articles) from RSS + http connectors. Dedup by
 * (source, externalId). `tags` stored as a JSON-encoded string.
 */
export const feedItems = pgTable(
  'feed_items',
  {
    source: text('source').notNull(),
    externalId: text('external_id').notNull(),
    title: text('title').notNull(),
    url: text('url').notNull(),
    summary: text('summary'),
    publishedAt: bigint('published_at', { mode: 'number' }).notNull(),
    tags: text('tags'),
  },
  (t) => ({
    uq: uniqueIndex('feed_src_extid_uq').on(t.source, t.externalId),
  }),
);
