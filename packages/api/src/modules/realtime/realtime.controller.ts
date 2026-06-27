import { Controller, Query, Sse, type MessageEvent } from '@nestjs/common';
import type { Observable } from 'rxjs';
import { map } from 'rxjs/operators';
import type { OHLCV } from '@tradeck/shared';
import { RealtimeGateway } from './realtime.gateway';

@Controller()
export class RealtimeController {
  constructor(private readonly gateway: RealtimeGateway) {}

  /** GET /api/stream?symbol=BTCUSDT — SSE of 1m candle updates. */
  @Sse('api/stream')
  stream(@Query('symbol') symbol = 'BTCUSDT'): Observable<MessageEvent> {
    return this.gateway
      .streamFor(symbol, '1m')
      .pipe(map((candle) => ({ data: candle as OHLCV })));
  }
}
