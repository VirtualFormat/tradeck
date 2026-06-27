import WebSocket, { type RawData } from 'ws';
import type { MarketTick, NormalizedEvent } from '@tradeck/shared';
import { BaseConnector } from '../base.connector';

/**
 * Push-type connector for Binance public WebSocket trade streams.
 * Subscribes to `<symbol>@trade` and normalizes each trade into a MarketTick.
 * No API key required (public market data).
 *
 * Resilience (collection isolation): errors are logged via emitError and never
 * thrown; a dropped connection reconnects with exponential backoff so a flaky
 * network or regional block cannot crash the process — other connectors keep
 * running.
 */
export class BinanceConnector extends BaseConnector {
  private ws?: WebSocket;
  private closed = false;
  private backoffMs = 1000;
  private openTimer?: NodeJS.Timeout;
  private static readonly MAX_BACKOFF_MS = 30_000;
  private static readonly OPEN_TIMEOUT_MS = 10_000;

  async start(): Promise<void> {
    this.closed = false;
    this.setStatus('starting');
    this.connect();
  }

  async stop(): Promise<void> {
    this.closed = true;
    if (this.openTimer) clearTimeout(this.openTimer);
    this.ws?.terminate();
    this.setStatus('stopped');
  }

  private connect(): void {
    const streams = this.config.symbols.map((s) => `${s.toLowerCase()}@trade`).join('/');
    const url = `wss://stream.binance.com:9443/ws/${streams}`;
    const ws = new WebSocket(url);
    this.ws = ws;

    // Abort a hanging handshake (TCP connects but TLS/WS upgrade never
    // completes — e.g. regional blocking) and fall back to reconnect.
    this.openTimer = setTimeout(() => {
      this.emitError(new Error('binance ws open timeout'));
      ws.terminate();
    }, BinanceConnector.OPEN_TIMEOUT_MS);

    ws.on('open', () => {
      if (this.openTimer) clearTimeout(this.openTimer);
      this.setStatus('running');
      this.backoffMs = 1000;
    });
    ws.on('message', (buf: RawData) => this.onMessage(buf));
    ws.on('ping', () => ws.pong());
    ws.on('error', (err) => this.emitError(err));
    ws.on('close', () => {
      if (this.openTimer) clearTimeout(this.openTimer);
      if (!this.closed) this.scheduleReconnect();
    });
  }

  private scheduleReconnect(): void {
    this.setStatus('error');
    const delay = this.backoffMs;
    setTimeout(() => {
      if (!this.closed) this.connect();
    }, delay);
    this.backoffMs = Math.min(this.backoffMs * 2, BinanceConnector.MAX_BACKOFF_MS);
  }

  private onMessage(buf: RawData): void {
    try {
      const raw = JSON.parse(buf.toString()) as {
        e?: string;
        s?: string;
        p?: string;
        q?: string;
        T?: number;
      };
      if (raw.e !== 'trade' || !raw.s || raw.p === undefined) return;
      const tick: MarketTick = {
        source: this.config.id,
        symbol: raw.s,
        ts: raw.T ?? Date.now(),
        price: Number(raw.p),
        volume: raw.q !== undefined ? Number(raw.q) : undefined,
      };
      const evt: NormalizedEvent = { kind: 'tick', payload: tick };
      this.emit(evt);
    } catch (err) {
      this.emitError(err);
    }
  }
}
