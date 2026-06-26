import { z } from 'zod';

/**
 * A news / article entry from an RSS or HTTP feed connector.
 * Dedup key downstream is `source` + `id` (source-native external id).
 */
export const FeedItemSchema = z.object({
  source: z.string().min(1),
  /** Source-native external id, used together with `source` for dedup. */
  id: z.string().min(1),
  title: z.string().min(1),
  url: z.string().url(),
  summary: z.string().optional(),
  /** Publish time, epoch milliseconds. */
  publishedAt: z.number().int().nonnegative(),
  tags: z.array(z.string()).optional(),
});

export type FeedItem = z.infer<typeof FeedItemSchema>;
