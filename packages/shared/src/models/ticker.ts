import { z } from 'zod';

/** Latest snapshot of a symbol plus its intraday change %, for overview/rank/heatmap. */
export const TickerSchema = z.object({
  source: z.string(),
  symbol: z.string(),
  price: z.number(),
  volume: z.number().optional(),
  ts: z.number(),
  /** intraday change fraction, e.g. 0.0123 = +1.23% (from latest 1m candle (c-o)/o) */
  changePct: z.number(),
  /** recent close prices (oldest→newest) for a background sparkline; may be empty */
  spark: z.array(z.number()).default([]),
  /** human-friendly display name when the source provides one */
  name: z.string().optional(),
  /** market grouping for the frontend tabs: 'cn' | 'hk' | 'us' | undefined */
  market: z.string().optional(),
  /** 今日开盘价 */
  open: z.number().optional(),
  /** 今日最高价 */
  high: z.number().optional(),
  /** 今日最低价 */
  low: z.number().optional(),
  /** 昨日收盘价 */
  prevClose: z.number().optional(),
  /** 绝对涨跌额（price - prevClose） */
  change: z.number().optional(),
  /** 成交额（元/港元/美元），与 volume(手) 区分 */
  amount: z.number().optional(),
  /** 振幅 fraction（0.0123 = 1.23%） */
  amplitude: z.number().optional(),
});
export type Ticker = z.infer<typeof TickerSchema>;
