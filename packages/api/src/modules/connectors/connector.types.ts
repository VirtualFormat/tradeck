import type { NormalizedEvent } from '@tradeck/shared';

export type ConnectorStatus = 'idle' | 'starting' | 'running' | 'stopped' | 'error';

export interface ConnectorConfig {
  /** connector instance id; also used as NormalizedEvent.source (e.g. "mock") */
  id: string;
  /** symbols to produce, e.g. ["BTCUSDT"] */
  symbols: string[];
  /** type-specific options (mock: intervalMs, startPrice, ...) */
  options?: Record<string, unknown>;
}

export interface ConnectorEvents {
  onData: (evt: NormalizedEvent) => void;
  onError: (err: unknown) => void;
  onStatus: (status: ConnectorStatus) => void;
}
