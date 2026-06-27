import type { NormalizedEvent } from '@tradeck/shared';
import { BaseConnector } from './base.connector';

/**
 * Skeleton for Pull-type connectors (RSS / REST / HTTP). Subclasses only
 * implement `fetchOnce()`; this base handles scheduling. Not wired up in the
 * MVP (only Mock runs) but kept as the extension point for future sources.
 */
export abstract class PollingConnector extends BaseConnector {
  private timer?: NodeJS.Timeout;
  // getter (not a field) so subclasses can read poll interval from this.config,
  // which is only assigned in init() — after construction.
  protected abstract get intervalMs(): number;
  protected abstract fetchOnce(): Promise<NormalizedEvent[]>;

  async start(): Promise<void> {
    this.setStatus('running');
    const poll = async (): Promise<void> => {
      try {
        const events = await this.fetchOnce();
        for (const evt of events) this.emit(evt);
      } catch (err) {
        this.emitError(err);
      }
    };
    void poll();
    this.timer = setInterval(() => void poll(), this.intervalMs);
  }

  async stop(): Promise<void> {
    if (this.timer) clearInterval(this.timer);
    this.setStatus('stopped');
  }
}
