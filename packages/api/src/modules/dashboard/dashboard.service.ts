import { Inject, Injectable } from '@nestjs/common';
import { eq } from 'drizzle-orm';
import type { DashboardLayout } from '@tradeck/shared';
import { DRIZZLE, type Database } from '../../infra/db/db.types';
import { dashboards } from '../../infra/db/schema';

const DEFAULT_ID = 'default';

/** 12-column default layout, roughly matching the original stacked design. */
const DEFAULT_LAYOUT: DashboardLayout = {
  items: [
    { i: 'overview', x: 0, y: 0, w: 12, h: 3, minW: 6, minH: 3 },
    { i: 'price', x: 0, y: 3, w: 7, h: 8, minW: 4, minH: 6 },
    { i: 'movers', x: 7, y: 3, w: 5, h: 8, minW: 3, minH: 6 },
    { i: 'heat', x: 0, y: 11, w: 6, h: 8, minW: 4, minH: 6 },
    { i: 'sectorVolume', x: 6, y: 11, w: 6, h: 8, minW: 4, minH: 6 },
    { i: 'graph', x: 0, y: 19, w: 7, h: 7, minW: 4, minH: 5 },
    { i: 'feed', x: 7, y: 19, w: 5, h: 7, minW: 3, minH: 5 },
  ],
};

@Injectable()
export class DashboardService {
  constructor(@Inject(DRIZZLE) private readonly db: Database) {}

  async getLayout(): Promise<DashboardLayout> {
    const [row] = await this.db
      .select()
      .from(dashboards)
      .where(eq(dashboards.id, DEFAULT_ID))
      .limit(1);
    return row?.layout ?? DEFAULT_LAYOUT;
  }

  async saveLayout(layout: DashboardLayout): Promise<DashboardLayout> {
    const now = Date.now();
    await this.db
      .insert(dashboards)
      .values({ id: DEFAULT_ID, layout, updatedAt: now })
      .onConflictDoUpdate({ target: dashboards.id, set: { layout, updatedAt: now } });
    return layout;
  }
}
