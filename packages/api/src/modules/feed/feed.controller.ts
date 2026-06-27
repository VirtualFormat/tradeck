import { Controller, Get, Query } from '@nestjs/common';
import type { FeedItem } from '@tradeck/shared';
import { FeedService } from './feed.service';

@Controller('api')
export class FeedController {
  constructor(private readonly svc: FeedService) {}

  /** GET /api/feed?limit=30 */
  @Get('feed')
  list(@Query('limit') limit = '30'): Promise<FeedItem[]> {
    return this.svc.list(Math.min(Number(limit) || 30, 100));
  }
}
