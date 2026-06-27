import {
  pgTable,
  text,
  doublePrecision,
  bigint,
  boolean,
  jsonb,
  uniqueIndex,
} from 'drizzle-orm/pg-core';
import type { DashboardLayout, DataSourceConfigJson } from '@tradeck/shared';

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

/**
 * Data source instances. Drives ConnectorManager: enabled rows are
 * instantiated + started on boot; CRUD mutations hot-reload them.
 * `id` doubles as ConnectorConfig.id and NormalizedEvent.source.
 */
export const dataSources = pgTable('data_sources', {
  id: text('id').primaryKey(),
  type: text('type').notNull(),
  name: text('name').notNull(),
  enabled: boolean('enabled').notNull().default(true),
  config: jsonb('config').notNull().$type<DataSourceConfigJson>(),
  createdAt: bigint('created_at', { mode: 'number' }).notNull(),
  updatedAt: bigint('updated_at', { mode: 'number' }).notNull(),
});

/** Persisted dashboard grid layout. Single global row (id='default') for now. */
export const dashboards = pgTable('dashboards', {
  id: text('id').primaryKey(),
  layout: jsonb('layout').notNull().$type<DashboardLayout>(),
  updatedAt: bigint('updated_at', { mode: 'number' }).notNull(),
});
