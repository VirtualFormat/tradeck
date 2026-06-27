import type { NormalizedEvent } from '@tradeck/shared';
import type { ConnectorConfig, ConnectorEvents, ConnectorStatus } from './connector.types';

/**
 * Unified connector lifecycle (architecture §2.2). Every data source — Push
 * (exchange WS) or Pull (REST/RSS/HTTP) — implements this contract and emits
 * only standard NormalizedEvents. A connector collects + normalizes + emits;
 * it never writes the DB or pushes to the frontend.
 */
export abstract class BaseConnector {
  protected config!: ConnectorConfig;
  private events!: ConnectorEvents;
  private status: ConnectorStatus = 'idle';

  init(config: ConnectorConfig, events: ConnectorEvents): void {
    this.config = config;
    this.events = events;
  }

  abstract start(): Promise<void>;
  abstract stop(): Promise<void>;

  health(): { id: string; status: ConnectorStatus } {
    return { id: this.config.id, status: this.status };
  }

  protected emit(evt: NormalizedEvent): void {
    this.events.onData(evt);
  }

  protected emitError(err: unknown): void {
    this.events.onError(err);
  }

  protected setStatus(status: ConnectorStatus): void {
    this.status = status;
    this.events.onStatus(status);
  }
}
