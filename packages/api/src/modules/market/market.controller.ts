import { Controller, Get, Query } from '@nestjs/common';
import type { OHLCV, OhlcvInterval } from '@tradeck/shared';
import { MarketService } from './market.service';

@Controller('api')
export class MarketController {
  constructor(private readonly svc: MarketService) {}

  /** GET /api/ohlcv?symbol=BTCUSDT&interval=1m&limit=500 */
  @Get('ohlcv')
  getOhlcv(
    @Query('symbol') symbol = 'BTCUSDT',
    @Query('interval') interval: OhlcvInterval = '1m',
    @Query('limit') limit = '500',
  ): Promise<OHLCV[]> {
    return this.svc.query(symbol, interval, Math.min(Number(limit) || 500, 1000));
  }
}
