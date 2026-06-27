import { Global, Inject, Module, type OnModuleDestroy } from '@nestjs/common';
import Redis from 'ioredis';
import { REDIS_CLIENT, REDIS_SUBSCRIBER } from './redis.tokens';

@Global()
@Module({
  providers: [
    {
      provide: REDIS_CLIENT,
      useFactory: () => new Redis(process.env.REDIS_URL ?? 'redis://redis:6379'),
    },
    {
      provide: REDIS_SUBSCRIBER,
      useFactory: () => new Redis(process.env.REDIS_URL ?? 'redis://redis:6379'),
    },
  ],
  exports: [REDIS_CLIENT, REDIS_SUBSCRIBER],
})
export class RedisModule implements OnModuleDestroy {
  constructor(
    @Inject(REDIS_CLIENT) private readonly client: Redis,
    @Inject(REDIS_SUBSCRIBER) private readonly subscriber: Redis,
  ) {}

  async onModuleDestroy(): Promise<void> {
    await Promise.all([this.client.quit(), this.subscriber.quit()]);
  }
}
