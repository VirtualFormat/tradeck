import { Module } from '@nestjs/common';
import { ConnectorsModule } from '../connectors/connectors.module';
import { DataSourcesController } from './datasources.controller';
import { DataSourcesService } from './datasources.service';

@Module({
  imports: [ConnectorsModule],
  controllers: [DataSourcesController],
  providers: [DataSourcesService],
})
export class DataSourcesModule {}
