import { Module } from '@nestjs/common';
import { IngestionModule } from '../ingestion/ingestion.module';
import { ConnectorManager } from './connector.manager';
import { ConnectorRegistry } from './connector.registry';

@Module({
  imports: [IngestionModule],
  providers: [ConnectorRegistry, ConnectorManager],
  exports: [ConnectorManager],
})
export class ConnectorsModule {}
