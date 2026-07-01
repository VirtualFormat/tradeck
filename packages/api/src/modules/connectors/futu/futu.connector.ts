import type { MarketTick, NormalizedEvent } from '@tradeck/shared';
import { BaseConnector } from '../base.connector';
import FutuWebsocket from 'futu-api';

const FUTU_MARKET = {
  hk: 1,
  us: 11,
  sh: 21,
  sz: 22,
} as const;

const SUB_TYPE_BASIC = 1;
const CMD_UPDATE_BASIC_QOT = 3005;

interface ParsedSymbol {
  symbol: string;
  security: { market: number; code: string };
}

interface FutuBasicQot {
  security?: { market?: number; code?: string };
  name?: string;
  curPrice?: number;
  volume?: unknown;
  hpVolume?: number;
  changeRate?: number;
  updateTimestamp?: number;
}

interface FutuQotPayload {
  retMsg?: string;
  s2c?: { basicQotList?: FutuBasicQot[] };
}

/**
 * Official Futu OpenAPI websocket connector. It talks to an already-running
 * Futu OpenD websocket gateway and emits normalized tick snapshots only.
 */
export class FutuConnector extends BaseConnector {
  private client?: FutuWebsocket;
  private timer?: NodeJS.Timeout;
  private securities: ParsedSymbol[] = [];

  async start(): Promise<void> {
    this.setStatus('starting');
    this.securities = this.config.symbols.map(parseSymbol).filter((s): s is ParsedSymbol => !!s);
    if (this.securities.length === 0) {
      this.emitError(new Error('futu connector has no valid symbols'));
      this.setStatus('error');
      return;
    }

    const host = stringOpt(this.config.options?.host) ?? process.env.FUTU_OPEND_HOST ?? 'futu-opend';
    const port = numberOpt(this.config.options?.port) ?? Number(process.env.FUTU_OPEND_PORT ?? 33333);
    const ssl = boolOpt(this.config.options?.ssl) ?? boolEnv(process.env.FUTU_OPEND_SSL) ?? false;
    const key = stringOpt(this.config.options?.key) ?? process.env.FUTU_OPEND_KEY;
    const intervalMs = numberOpt(this.config.options?.intervalMs) ?? 3000;

    const client = new FutuWebsocket();
    this.client = client;
    client.onlogin = (ok, msg) => {
      if (!ok) {
        this.emitError(new Error(`futu login failed: ${stringifyError(msg)}`));
        this.setStatus('error');
        return;
      }
      this.setStatus('running');
      void this.subscribe();
      void this.fetchSnapshot();
      this.timer = setInterval(() => void this.fetchSnapshot(), intervalMs);
    };
    client.onPush = (cmd, payload) => {
      if (cmd !== CMD_UPDATE_BASIC_QOT) return;
      this.ingestQots(payload as FutuQotPayload);
    };

    try {
      client.start(host, port, ssl, key);
    } catch (err) {
      this.emitError(err);
      this.setStatus('error');
    }
  }

  async stop(): Promise<void> {
    if (this.timer) clearInterval(this.timer);
    this.timer = undefined;
    if (this.client) {
      this.client.stop();
      const raw = this.client as unknown as { websock?: { close?: () => void } };
      raw.websock?.close?.();
    }
    this.client = undefined;
    this.setStatus('stopped');
  }

  private async subscribe(): Promise<void> {
    if (!this.client) return;
    try {
      await this.client.Sub({
        c2s: {
          securityList: this.securities.map((s) => s.security),
          subTypeList: [SUB_TYPE_BASIC],
          isSubOrUnSub: true,
          isRegOrUnRegPush: true,
          isFirstPush: true,
        },
      });
    } catch (err) {
      this.emitError(new Error(`futu subscribe failed: ${stringifyError(err)}`));
    }
  }

  private async fetchSnapshot(): Promise<void> {
    if (!this.client) return;
    try {
      const payload = await this.client.GetBasicQot({
        c2s: { securityList: this.securities.map((s) => s.security) },
      });
      this.ingestQots(payload as FutuQotPayload);
    } catch (err) {
      this.emitError(new Error(`futu snapshot failed: ${stringifyError(err)}`));
    }
  }

  private ingestQots(payload: FutuQotPayload): void {
    const rows = payload.s2c?.basicQotList;
    if (!Array.isArray(rows)) return;
    for (const row of rows) {
      const evt = this.normalize(row);
      if (evt) this.emit(evt);
    }
  }

  private normalize(row: FutuBasicQot): NormalizedEvent | null {
    const price = typeof row.curPrice === 'number' && row.curPrice > 0 ? row.curPrice : null;
    const market = row.security?.market;
    const code = row.security?.code;
    if (price === null || typeof market !== 'number' || !code) return null;
    const updateTs = typeof row.updateTimestamp === 'number' ? row.updateTimestamp : undefined;
    const ts = updateTs ? (updateTs < 1_000_000_000_000 ? updateTs * 1000 : updateTs) : Date.now();
    const tick: MarketTick = {
      source: this.config.id,
      symbol: `${marketPrefix(market)}.${code}`,
      ts: Math.trunc(ts),
      price,
      volume: numberFromLong(row.hpVolume ?? row.volume),
      changePct: typeof row.changeRate === 'number' ? row.changeRate / 100 : undefined,
      name: row.name,
    };
    return { kind: 'tick', payload: tick };
  }
}

function parseSymbol(raw: string): ParsedSymbol | null {
  const [prefixRaw, codeRaw] = raw.includes('.') ? raw.split('.', 2) : ['CN', raw];
  const prefix = prefixRaw.toLowerCase();
  const code = codeRaw.trim().toUpperCase();
  if (!code) return null;
  const market =
    prefix === 'hk' ? FUTU_MARKET.hk :
    prefix === 'us' ? FUTU_MARKET.us :
    prefix === 'sh' ? FUTU_MARKET.sh :
    prefix === 'sz' ? FUTU_MARKET.sz :
    inferCnMarket(code);
  if (!market) return null;
  return { symbol: `${prefix.toUpperCase()}.${code}`, security: { market, code } };
}

function inferCnMarket(code: string): number | null {
  if (/^(5|6|9)/.test(code)) return FUTU_MARKET.sh;
  if (/^(0|1|2|3)/.test(code)) return FUTU_MARKET.sz;
  return null;
}

function marketPrefix(market: number): string {
  if (market === FUTU_MARKET.hk) return 'HK';
  if (market === FUTU_MARKET.us) return 'US';
  if (market === FUTU_MARKET.sh) return 'SH';
  if (market === FUTU_MARKET.sz) return 'SZ';
  return String(market);
}

function stringOpt(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim() ? value.trim() : undefined;
}

function numberOpt(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined;
}

function boolOpt(value: unknown): boolean | undefined {
  return typeof value === 'boolean' ? value : undefined;
}

function boolEnv(value: string | undefined): boolean | undefined {
  if (!value) return undefined;
  return ['1', 'true', 'yes', 'on'].includes(value.toLowerCase());
}

function numberFromLong(value: unknown): number | undefined {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (value && typeof (value as { toNumber?: () => number }).toNumber === 'function') {
    const n = (value as { toNumber: () => number }).toNumber();
    return Number.isFinite(n) ? n : undefined;
  }
  return undefined;
}

function stringifyError(value: unknown): string {
  if (value instanceof Error) return value.message;
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}
