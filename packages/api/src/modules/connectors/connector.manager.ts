import {
  Injectable,
  Logger,
  type OnApplicationBootstrap,
  type OnModuleDestroy,
} from '@nestjs/common';
import { IngestionService } from '../ingestion/ingestion.service';
import { BaseConnector } from './base.connector';
import { BinanceConnector } from './binance/binance.connector';
import type { ConnectorConfig } from './connector.types';
import { ConnectorRegistry } from './connector.registry';
import { MockConnector } from './mock/mock.connector';

/**
 * Wires connectors to the ingestion pipeline and manages their lifecycle.
 * MVP: hard-codes a single mock instance. Future: read DB `data_sources`
 * config and hot-reload.
 */
@Injectable()
export class ConnectorManager implements OnApplicationBootstrap, OnModuleDestroy {
  private readonly logger = new Logger(ConnectorManager.name);
  private readonly running: BaseConnector[] = [];

  constructor(
    private readonly registry: ConnectorRegistry,
    private readonly ingestion: IngestionService,
  ) {}

  onApplicationBootstrap(): void {
    this.registry.register('mock', () => new MockConnector());
    this.registry.register('binance', () => new BinanceConnector());

    // Real source: Binance public WS trade stream.
    this.startConnector('binance', { id: 'binance', symbols: ['BTCUSDT'] });
    // Fallback/demo source: mock random-walk on a separate symbol.
    this.startConnector('mock', {
      id: 'mock',
      symbols: ['MOCKUSDT'],
      options: { intervalMs: 300, startPrice: 65000 },
    });
  }

  private startConnector(type: string, config: ConnectorConfig): void {
    const connector = this.registry.create(type);
    connector.init(config, {
      onData: (evt) => void this.ingestion.ingest(evt),
      onError: (err) => this.logger.error(`connector ${config.id} error`, err),
      onStatus: (status) => this.logger.log(`connector ${config.id} status: ${status}`),
    });
    void connector.start();
    this.running.push(connector);
  }

  async onModuleDestroy(): Promise<void> {
    await Promise.all(this.running.map((c) => c.stop()));
  }
}
