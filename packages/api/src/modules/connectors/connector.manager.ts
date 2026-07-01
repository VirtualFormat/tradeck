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
import { EastmoneyConnector } from './eastmoney/eastmoney.connector';
import { FutuConnector } from './futu/futu.connector';
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
    this.registry.register('eastmoney', () => new EastmoneyConnector());
    this.registry.register('futu', () => new FutuConnector());
    this.registry.register('mock-feed', () => new MockFeedConnector());
    this.registry.register('rss', () => new RssConnector());
    this.registry.register('http-json', () => new HttpJsonConnector());

    await this.seedIfEmpty();
    await this.seedMissingFutuSources();
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
        id: 'eastmoney-cn',
        type: 'eastmoney',
        name: '东方财富 · A股',
        enabled: true,
        config: {
          // secids: 1.=SH, 0.=SZ
          symbols: ['1.000001', '1.600519', '0.300750', '0.000858', '1.601318'],
          options: { market: 'cn', intervalMs: 3000 },
        },
        createdAt: now,
        updatedAt: now,
      },
      {
        id: 'eastmoney-hk',
        type: 'eastmoney',
        name: '东方财富 · 港股',
        enabled: true,
        config: {
          symbols: ['116.00700', '116.09988', '116.03690', '100.HSI'],
          options: { market: 'hk', intervalMs: 3000 },
        },
        createdAt: now,
        updatedAt: now,
      },
      {
        id: 'eastmoney-us',
        type: 'eastmoney',
        name: '东方财富 · 美股',
        enabled: true,
        config: {
          symbols: ['105.AAPL', '105.TSLA', '105.NVDA', '105.MSFT', '105.AMZN'],
          options: { market: 'us', intervalMs: 3000 },
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
    this.logger.log('seeded default data_sources');
  }

  private async seedMissingFutuSources(): Promise<void> {
    const now = Date.now();
    const enabled = /^(true|1|yes|on)$/i.test(process.env.FUTU_DEFAULT_ENABLED ?? '');
    const host = process.env.FUTU_OPEND_HOST ?? 'futu-opend';
    const port = Number(process.env.FUTU_OPEND_PORT ?? 33333);
    const ssl = /^(true|1|yes|on)$/i.test(process.env.FUTU_OPEND_SSL ?? 'true');
    const key = process.env.FUTU_OPEND_KEY ?? 'tradeck-local-opend';
    const defaults = [
      {
        id: 'futu-cn',
        type: 'futu',
        name: 'Futu OpenD · A股',
        enabled,
        config: {
          symbols: ['SH.600519', 'SZ.300750', 'SZ.000858', 'SH.601318', 'SZ.000001'],
          options: { market: 'cn', host, port, ssl, key, intervalMs: 3000 },
        },
        createdAt: now,
        updatedAt: now,
      },
      {
        id: 'futu-hk',
        type: 'futu',
        name: 'Futu OpenD · 港股',
        enabled,
        config: {
          symbols: ['HK.00700', 'HK.09988', 'HK.03690', 'HK.00941', 'HK.01810'],
          options: { market: 'hk', host, port, ssl, key, intervalMs: 3000 },
        },
        createdAt: now,
        updatedAt: now,
      },
      {
        id: 'futu-us',
        type: 'futu',
        name: 'Futu OpenD · 美股',
        enabled,
        config: {
          symbols: ['US.AAPL', 'US.TSLA', 'US.NVDA', 'US.MSFT', 'US.AMZN'],
          options: { market: 'us', host, port, ssl, key, intervalMs: 3000 },
        },
        createdAt: now,
        updatedAt: now,
      },
    ];
    await this.db
      .insert(dataSources)
      .values(defaults)
      .onConflictDoNothing({ target: dataSources.id });
    for (const item of defaults) {
      await this.db
        .update(dataSources)
        .set({ config: item.config, updatedAt: now })
        .where(eq(dataSources.id, item.id));
    }
  }
}
