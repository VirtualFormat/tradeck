import {
  Inject,
  Injectable,
  type OnModuleDestroy,
  type OnModuleInit,
} from '@nestjs/common';
import type Redis from 'ioredis';
import { Observable, Subject } from 'rxjs';
import { filter, map } from 'rxjs/operators';
import { REDIS_SUBSCRIBER } from '../../infra/redis/redis.tokens';

/**
 * Fan-out hub: subscribes to Redis candle channels and exposes a filtered
 * stream per symbol. This is the replaceable realtime gateway — swapping SSE
 * for native ws later only touches this layer + the controller.
 */
@Injectable()
export class RealtimeGateway implements OnModuleInit, OnModuleDestroy {
  private readonly stream$ = new Subject<{ channel: string; data: unknown }>();

  constructor(@Inject(REDIS_SUBSCRIBER) private readonly sub: Redis) {}

  async onModuleInit(): Promise<void> {
    await this.sub.psubscribe('candle:*');
    this.sub.on('pmessage', (_pattern: string, channel: string, message: string) => {
      try {
        this.stream$.next({ channel, data: JSON.parse(message) });
      } catch {
        /* ignore malformed messages */
      }
    });
  }

  streamFor(symbol: string, interval = '1m'): Observable<unknown> {
    const target = `candle:${symbol}:${interval}`;
    return this.stream$.pipe(
      filter((m) => m.channel === target),
      map((m) => m.data),
    );
  }

  onModuleDestroy(): void {
    this.stream$.complete();
  }
}
