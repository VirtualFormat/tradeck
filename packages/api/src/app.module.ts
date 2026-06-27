import { Module } from '@nestjs/common';
import { HealthController } from './health.controller';
import { ConfigModule } from './infra/config/config.module';
import { DbModule } from './infra/db/db.module';
import { RedisModule } from './infra/redis/redis.module';
import { ConnectorsModule } from './modules/connectors/connectors.module';
import { FeedModule } from './modules/feed/feed.module';
import { IngestionModule } from './modules/ingestion/ingestion.module';
import { MarketModule } from './modules/market/market.module';
import { RealtimeModule } from './modules/realtime/realtime.module';

@Module({
  imports: [
    ConfigModule,
    DbModule,
    RedisModule,
    IngestionModule,
    MarketModule,
    RealtimeModule,
    FeedModule,
    ConnectorsModule,
  ],
  controllers: [HealthController],
})
export class AppModule {}
