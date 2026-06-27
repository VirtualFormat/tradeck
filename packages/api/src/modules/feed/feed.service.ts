import { Inject, Injectable } from '@nestjs/common';
import { desc } from 'drizzle-orm';
import type { FeedItem } from '@tradeck/shared';
import { DRIZZLE, type Database } from '../../infra/db/db.types';
import { feedItems } from '../../infra/db/schema';

@Injectable()
export class FeedService {
  constructor(@Inject(DRIZZLE) private readonly db: Database) {}

  async list(limit: number): Promise<FeedItem[]> {
    const rows = await this.db
      .select()
      .from(feedItems)
      .orderBy(desc(feedItems.publishedAt))
      .limit(limit);
    return rows.map((r) => ({
      source: r.source,
      id: r.externalId,
      title: r.title,
      url: r.url,
      summary: r.summary ?? undefined,
      publishedAt: r.publishedAt,
      tags: r.tags ? (JSON.parse(r.tags) as string[]) : undefined,
    }));
  }
}
