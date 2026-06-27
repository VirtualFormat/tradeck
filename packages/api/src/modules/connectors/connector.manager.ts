import {
  Inject,
  Injectable,
  Logger,
  type OnApplicationBootstrap,
  type OnModuleDestroy,
} from '@nestjs/common';
import { eq, sql } from 'drizzle-orm';
import type { ConnectorStatus, DataSource } from '@tradeck/shared';
import { DRIZZLE, type Database } from '../../infra/db/db.types';
import { dataSources } from '../../infra/db/schema';
import { IngestionService } from '../ingestion/ingestion.service';
import { BaseConnector } from './base.connector';
import { BinanceConnector } from './binance/binance.connector';
import { ConnectorRegistry } from './connector.registry';
import { HttpJsonConnector } from './http-json/http-json.connector';
import { MockConnector } from './mock/mock.connector';
import { MockFeedConnector } from './mock/mock-feed.connector';
import { RssConnector } from './rss/rss.connector';

interface RunningInstance {
  type: string;
  connector: BaseConnector;
}

type Row = typeof dataSources.$inferSelect;
function rowToDataSource(r: Row): DataSource {
  return r as unknown as DataSource;
}

/**
 * Config-driven connector lifecycle. Reads enabled data_sources on boot,
 * instantiates + starts connectors (indexed by id), and hot-reloads on CRUD
 * mutations (stop old instance, start new) without restarting the process.
 */
@Injectable()
export class ConnectorManager implements OnApplicationBootstrap, OnModuleDestroy {
  private readonly logger = new Logger(ConnectorManager.name);
  private readonly instances = new Map<string, RunningInstance>();

  constructor(
    private readonly registry: ConnectorRegistry,
    private readonly ingestion: IngestionService,
    @Inject(DRIZZLE) private readonly db: Database,
  ) {}

  async onApplicationBootstrap(): Promise<void> {
    this.registry.register('mock', () => new MockConnector());
    this.registry.register('binance', () => new BinanceConnector());
    this.registry.register('mock-feed', () => new MockFeedConnector());
    this.registry.register('rss', () => new RssConnector());
    this.registry.register('http-json', () => new HttpJsonConnector());

    await this.seedIfEmpty();
    await this.reloadAll();
  }

  async onModuleDestroy(): Promise<void> {
    await Promise.all([...this.instances.values()].map((i) => i.connector.stop()));
    this.instances.clear();
  }

  healthAll(): { id: string; type: string; status: ConnectorStatus }[] {
    return [...this.instances.entries()].map(([id, inst]) => ({
      id,
      type: inst.type,
      status: inst.connector.health().status as ConnectorStatus,
    }));
  }

  async reloadAll(): Promise<void> {
    await Promise.all([...this.instances.values()].map((i) => i.connector.stop()));
    this.instances.clear();
    const rows = await this.db.select().from(dataSources).where(eq(dataSources.enabled, true));
    for (const row of rows) await this.startInstance(rowToDataSource(row));
  }

  async reloadOne(id: string): Promise<void> {
    const existing = this.instances.get(id);
    if (existing) {
      await existing.connector.stop();
      this.instances.delete(id);
    }
    const [row] = await this.db.select().from(dataSources).where(eq(dataSources.id, id)).limit(1);
    if (row && row.enabled) {
      await this.startInstance(rowToDataSource(row));
      this.logger.log(`reloadOne(${id}): started`);
    } else {
      this.logger.log(`reloadOne(${id}): stopped`);
    }
  }

  async stopOne(id: string): Promise<void> {
    const existing = this.instances.get(id);
    if (existing) {
      await existing.connector.stop();
      this.instances.delete(id);
      this.logger.log(`stopOne(${id})`);
    }
  }

  private async startInstance(row: DataSource): Promise<void> {
    const connector = this.registry.create(row.type);
    connector.init(
      { id: row.id, symbols: row.config.symbols, options: row.config.options },
      {
        onData: (evt) => void this.ingestion.ingest(evt),
        onError: (err) => this.logger.error(`connector ${row.id} error`, err),
        onStatus: (status) => this.logger.log(`connector ${row.id} status: ${status}`),
      },
    );
    await connector.start();
    this.instances.set(row.id, { type: row.type, connector });
  }

  private async seedIfEmpty(): Promise<void> {
    const [{ count }] = await this.db
      .select({ count: sql<number>`count(*)` })
      .from(dataSources);
    if (Number(count) > 0) return;
    const now = Date.now();
    await this.db.insert(dataSources).values([
      {
        id: 'binance',
        type: 'binance',
        name: 'Binance BTC/USDT',
        enabled: true,
        config: { symbols: ['BTCUSDT'], options: {} },
        createdAt: now,
        updatedAt: now,
      },
      {
        id: 'mock',
        type: 'mock',
        name: 'Mock Market (random walk)',
        enabled: true,
        config: {
          symbols: ['MOCKUSDT', 'MOCKETH', 'MOCKSOL'],
          options: {
            intervalMs: 300,
            startPrices: { MOCKUSDT: 65000, MOCKETH: 3400, MOCKSOL: 180 },
          },
        },
        createdAt: now,
        updatedAt: now,
      },
      {
        id: 'sina-finance',
        type: 'rss',
        name: 'Sina Finance RSS',
        enabled: true,
        config: {
          symbols: [],
          options: { url: 'https://rss.sina.com.cn/roll/finance/hot_roll.xml' },
        },
        createdAt: now,
        updatedAt: now,
      },
      {
        id: 'mock-feed',
        type: 'mock-feed',
        name: 'Mock Feed (synthetic)',
        enabled: true,
        config: { symbols: [], options: { intervalMs: 8000 } },
        createdAt: now,
        updatedAt: now,
      },
    ]);
    this.logger.log('seeded 4 default data_sources');
  }
}
