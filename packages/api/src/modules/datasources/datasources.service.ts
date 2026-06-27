import { BadRequestException, Inject, Injectable, NotFoundException } from '@nestjs/common';
import { asc, eq } from 'drizzle-orm';
import {
  type ConnectorStatus,
  CreateDataSourceSchema,
  type DataSource,
  type DataSourceWithHealth,
  UpdateDataSourceSchema,
} from '@tradeck/shared';
import { DRIZZLE, type Database } from '../../infra/db/db.types';
import { dataSources } from '../../infra/db/schema';
import { ConnectorManager } from '../connectors/connector.manager';

type Row = typeof dataSources.$inferSelect;
function rowToDataSource(r: Row): DataSource {
  return r as unknown as DataSource;
}

@Injectable()
export class DataSourcesService {
  constructor(
    @Inject(DRIZZLE) private readonly db: Database,
    private readonly manager: ConnectorManager,
  ) {}

  async list(): Promise<DataSourceWithHealth[]> {
    const rows = await this.db.select().from(dataSources).orderBy(asc(dataSources.createdAt));
    const health = new Map(this.manager.healthAll().map((h) => [h.id, h.status]));
    return rows.map((r) => {
      const ds = rowToDataSource(r);
      const status: ConnectorStatus = health.get(r.id) ?? (r.enabled ? 'unknown' : 'stopped');
      return { ...ds, status };
    });
  }

  async create(body: unknown): Promise<DataSource> {
    const dto = this.parse(CreateDataSourceSchema, body);
    const now = Date.now();
    await this.db
      .insert(dataSources)
      .values({ ...dto, createdAt: now, updatedAt: now });
    await this.manager.reloadOne(dto.id);
    return this.getOne(dto.id);
  }

  async update(id: string, body: unknown): Promise<DataSource> {
    const dto = this.parse(UpdateDataSourceSchema, body);
    const res = await this.db
      .update(dataSources)
      .set({ ...dto, updatedAt: Date.now() })
      .where(eq(dataSources.id, id))
      .returning();
    if (res.length === 0) throw new NotFoundException(`data source ${id} not found`);
    await this.manager.reloadOne(id);
    return this.getOne(id);
  }

  async remove(id: string): Promise<{ ok: true }> {
    await this.manager.stopOne(id);
    await this.db.delete(dataSources).where(eq(dataSources.id, id));
    return { ok: true };
  }

  private async getOne(id: string): Promise<DataSource> {
    const [row] = await this.db.select().from(dataSources).where(eq(dataSources.id, id)).limit(1);
    if (!row) throw new NotFoundException(`data source ${id} not found`);
    return rowToDataSource(row);
  }

  private parse<T>(schema: { parse: (v: unknown) => T }, body: unknown): T {
    try {
      return schema.parse(body);
    } catch (err) {
      // ZodError shape (avoid importing zod, not a direct api dep)
      const issues = (err as { issues?: { path: (string | number)[]; message: string }[] }).issues;
      if (Array.isArray(issues)) {
        throw new BadRequestException(issues.map((i) => `${i.path.join('.')}: ${i.message}`));
      }
      throw err;
    }
  }
}
