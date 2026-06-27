import type { MarketTick, NormalizedEvent } from '@tradeck/shared';
import { BaseConnector } from '../base.connector';

/**
 * Mock Push-type connector: emits a random-walk MarketTick per symbol on a
 * timer. Used to exercise the full pipeline without external deps.
 */
export class MockConnector extends BaseConnector {
  private timer?: NodeJS.Timeout;
  private readonly lastPrice = new Map<string, number>();

  async start(): Promise<void> {
    this.setStatus('running');
    const intervalMs = (this.config.options?.intervalMs as number) ?? 300;
    this.timer = setInterval(() => this.produce(), intervalMs);
  }

  async stop(): Promise<void> {
    if (this.timer) clearInterval(this.timer);
    this.setStatus('stopped');
  }

  private produce(): void {
    const startPrice = (this.config.options?.startPrice as number) ?? 65000;
    for (const symbol of this.config.symbols) {
      const prev = this.lastPrice.get(symbol) ?? startPrice;
      const next = Math.max(1, prev + (Math.random() - 0.5) * prev * 0.001);
      this.lastPrice.set(symbol, next);
      this.emit(this.normalize(symbol, next));
    }
  }

  private normalize(symbol: string, price: number): NormalizedEvent {
    const tick: MarketTick = {
      source: this.config.id,
      symbol,
      ts: Date.now(),
      price,
      volume: Math.random() * 2,
    };
    return { kind: 'tick', payload: tick };
  }
}
