import { Global, Module } from '@nestjs/common';

export interface AppConfig {
  databaseUrl: string;
  redisUrl: string;
  apiPort: number;
}

export const APP_CONFIG = 'APP_CONFIG';

@Global()
@Module({
  providers: [
    {
      provide: APP_CONFIG,
      useFactory: (): AppConfig => ({
        databaseUrl: process.env.DATABASE_URL ?? 'postgres://tradeck:tradeck@postgres:5432/tradeck',
        redisUrl: process.env.REDIS_URL ?? 'redis://redis:6379',
        apiPort: Number(process.env.API_PORT ?? 3000),
      }),
    },
  ],
  exports: [APP_CONFIG],
})
export class ConfigModule {}
