import { z } from 'zod';

export const MarketDepthStockSchema = z.object({
  id: z.string(),
  symbol: z.string(),
  name: z.string(),
  sectorId: z.string(),
  price: z.number(),
  changePct: z.number(),
  turnover: z.number(),
  volume: z.number(),
});
export type MarketDepthStock = z.infer<typeof MarketDepthStockSchema>;

export const MarketDepthSectorSchema = z.object({
  id: z.string(),
  name: z.string(),
  market: z.string(),
  indexValue: z.number(),
  changePct: z.number(),
  turnover: z.number(),
  heat: z.number(),
  marketCap: z.number(),
  history: z.array(z.number()),
  stocks: z.array(MarketDepthStockSchema),
});
export type MarketDepthSector = z.infer<typeof MarketDepthSectorSchema>;

export const MarketDepthResponseSchema = z.object({
  source: z.string(),
  market: z.string(),
  delayed: z.boolean().default(false),
  sectors: z.array(MarketDepthSectorSchema),
  updatedAt: z.number(),
});
export type MarketDepthResponse = z.infer<typeof MarketDepthResponseSchema>;
