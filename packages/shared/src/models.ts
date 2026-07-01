import { z } from 'zod';

/**
 * Tradeck 标准数据模型 —— 所有数据源的 normalize() 必须输出这四类之一。
 * 前后端共享，是契约的单一来源。
 */

/** 最新报价 / 实时 tick */
export const MarketTickSchema = z.object({
  source: z.string(),
  symbol: z.string(),
  ts: z.number(), // epoch ms
  price: z.number(),
  change: z.number().optional(), // 绝对涨跌
  changePercent: z.number().optional(), // 涨跌幅 %
  volume: z.number().optional(),
  name: z.string().optional(), // 展示名（如「苹果」）
  currency: z.string().optional(),
});
export type MarketTick = z.infer<typeof MarketTickSchema>;

/** K 线 */
export const OHLCVSchema = z.object({
  source: z.string(),
  symbol: z.string(),
  interval: z.string(), // 1d / 1h / 5m ...
  ts: z.number(), // bar 起始 epoch ms
  o: z.number(),
  h: z.number(),
  l: z.number(),
  c: z.number(),
  v: z.number().optional(),
});
export type OHLCV = z.infer<typeof OHLCVSchema>;

/** 资讯流条目 */
export const FeedItemSchema = z.object({
  source: z.string(),
  id: z.string(), // source + externalId 去重用
  title: z.string(),
  url: z.string(),
  summary: z.string().optional(),
  publishedAt: z.number().optional(), // epoch ms
  tags: z.array(z.string()).optional(),
});
export type FeedItem = z.infer<typeof FeedItemSchema>;

/** 自定义 HTTP 源兜底 */
export const GenericMetricSchema = z.object({
  source: z.string(),
  key: z.string(),
  ts: z.number(),
  value: z.number(),
  meta: z.record(z.unknown()).optional(),
});
export type GenericMetric = z.infer<typeof GenericMetricSchema>;

/** API 响应包装 */
export const QuoteResponseSchema = z.object({
  ticks: z.array(MarketTickSchema),
  fetchedAt: z.number(),
});
export type QuoteResponse = z.infer<typeof QuoteResponseSchema>;

export const FeedResponseSchema = z.object({
  items: z.array(FeedItemSchema),
  fetchedAt: z.number(),
});
export type FeedResponse = z.infer<typeof FeedResponseSchema>;
