import { Body, Controller, Delete, Get, Param, Patch, Post } from '@nestjs/common';
import type { DataSource, DataSourceWithHealth } from '@tradeck/shared';
import { DataSourcesService } from './datasources.service';

@Controller('api')
export class DataSourcesController {
  constructor(private readonly svc: DataSourcesService) {}

  @Get('datasources')
  list(): Promise<DataSourceWithHealth[]> {
    return this.svc.list();
  }

  @Post('datasources')
  create(@Body() body: unknown): Promise<DataSource> {
    return this.svc.create(body);
  }

  @Patch('datasources/:id')
  update(@Param('id') id: string, @Body() body: unknown): Promise<DataSource> {
    return this.svc.update(id, body);
  }

  @Delete('datasources/:id')
  remove(@Param('id') id: string): Promise<{ ok: true }> {
    return this.svc.remove(id);
  }
}
