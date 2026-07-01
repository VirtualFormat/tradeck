import { Inject, Injectable, Logger } from '@nestjs/common';
import { and, desc, eq } from 'drizzle-orm';
import type Redis from 'ioredis';
import FutuWebsocket from 'futu-api';
import type {
  MarketDepthResponse,
  MarketDepthSector,
  MarketDepthStock,
  MarketTick,
  OHLCV,
  OhlcvInterval,
  Ticker,
} from '@tradeck/shared';
import { DRIZZLE, type Database } from '../../infra/db/db.types';
import { ohlcv } from '../../infra/db/schema';
import { REDIS_CLIENT } from '../../infra/redis/redis.tokens';

/** Derive the frontend market tab from connector ids like eastmoney-cn/futu-hk. */
function marketOf(source: string): string | undefined {
  const m = /^(eastmoney|futu)-(cn|hk|us)$/.exec(source);
  return m ? m[2] : undefined;
}

@Injectable()
export class MarketService {
  private readonly logger = new Logger(MarketService.name);
  private readonly depthCache = new Map<string, { expiresAt: number; data: MarketDepthResponse }>();

  constructor(
    @Inject(DRIZZLE) private readonly db: Database,
    @Inject(REDIS_CLIENT) private readonly redis: Redis,
  ) {}

  async query(symbol: string, interval: OhlcvInterval, limit: number): Promise<OHLCV[]> {
    const rows = await this.db
      .select()
      .from(ohlcv)
      .where(and(eq(ohlcv.symbol, symbol), eq(ohlcv.interval, interval)))
      .orderBy(desc(ohlcv.ts))
      .limit(limit);
    // SQL returns newest-first; charts want oldest-first.
    return rows.reverse() as OHLCV[];
  }

  /**
   * All latest per-symbol snapshots (from Redis `latest:{source}:{symbol}`),
   * enriched with intraday change% from the current 1m candle (c-o)/o.
   * Drives the overview / movers / heatmap panels.
   */
  async listTickers(): Promise<Ticker[]> {
    const keys = await this.redis.keys('latest:*');
    if (keys.length === 0) return [];
    const raws = await this.redis.mget(keys);
    const tickers: Ticker[] = [];
    for (const raw of raws) {
      if (!raw) continue;
      let tick: MarketTick;
      try {
        tick = JSON.parse(raw) as MarketTick;
      } catch {
        continue;
      }
      const recent = await this.recentCloses(tick.symbol, 30);
      // Prefer the source's reported day-change (e.g. stock quotes); otherwise
      // fall back to the intraminute delta vs the current 1m candle open.
      const open = recent.opens.at(-1);
      const changePct =
        tick.changePct ?? (open && open !== 0 ? (tick.price - open) / open : 0);
      // sparkline = recent closes oldest→newest, with the live price as the tip
      const spark = recent.closes.length > 0 ? [...recent.closes, tick.price] : [];
      tickers.push({
        source: tick.source,
        symbol: tick.symbol,
        price: tick.price,
        volume: tick.volume,
        ts: tick.ts,
        changePct,
        spark,
        name: tick.name,
        market: marketOf(tick.source),
      });
    }
    return tickers.sort((a, b) => b.changePct - a.changePct);
  }

  async getMarketDepth(source: string, market: string): Promise<MarketDepthResponse> {
    const normalizedSource = source === 'auto' ? 'futu' : source;
    const key = `${normalizedSource}:${market}`;
    const cached = this.depthCache.get(key);
    if (cached && cached.expiresAt > Date.now()) return cached.data;

    let data: MarketDepthResponse;
    if (normalizedSource === 'yahoo' || (normalizedSource === 'futu' && market === 'us')) {
      data = await this.yahooIndexDepth(market);
    } else if (normalizedSource === 'futu') {
      data = await this.futuMarketDepth(market);
    } else {
      data = { source: normalizedSource, market, delayed: false, sectors: [], updatedAt: Date.now() };
    }
    this.depthCache.set(key, { expiresAt: Date.now() + 10_000, data });
    return data;
  }

  /** Recent 1m candles (oldest→newest) as parallel opens/closes arrays. */
  private async recentCloses(
    symbol: string,
    limit: number,
  ): Promise<{ opens: number[]; closes: number[] }> {
    const rows = await this.db
      .select()
      .from(ohlcv)
      .where(and(eq(ohlcv.symbol, symbol), eq(ohlcv.interval, '1m')))
      .orderBy(desc(ohlcv.ts))
      .limit(limit);
    rows.reverse(); // newest-first → oldest-first
    return { opens: rows.map((r) => r.o), closes: rows.map((r) => r.c) };
  }

  private async yahooIndexDepth(market: string): Promise<MarketDepthResponse> {
    if (market !== 'us') {
      return { source: 'yahoo', market, delayed: true, sectors: [], updatedAt: Date.now() };
    }
    const symbols = [
      ['^GSPC', '标普500'],
      ['^IXIC', '纳斯达克综合'],
      ['^DJI', '道琼斯工业'],
      ['^RUT', '罗素2000'],
      ['^VIX', 'VIX波动率'],
    ] as const;
    const rows = await Promise.all(
      symbols.map(async ([symbol, name]) => this.fetchYahooIndex(symbol, name)),
    );
    return {
      source: 'yahoo',
      market,
      delayed: true,
      sectors: rows.filter((row): row is MarketDepthSector => !!row),
      updatedAt: Date.now(),
    };
  }

  private async fetchYahooIndex(symbol: string, name: string): Promise<MarketDepthSector | null> {
    const url = `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(symbol)}?range=1d&interval=5m`;
    try {
      const res = await fetch(url, {
        headers: { 'User-Agent': 'Mozilla/5.0 Tradeck/0.1' },
        signal: AbortSignal.timeout(7000),
      });
      if (!res.ok) return null;
      const json = asRecord(await res.json());
      const result = asRecord(asArray(asRecord(json.chart).result)[0]);
      const meta = asRecord(result.meta);
      const price = num(meta.regularMarketPrice) ?? 0;
      const previous = num(meta.chartPreviousClose) ?? num(meta.previousClose) ?? price;
      if (price <= 0) return null;
      const closes = asArray(
        asRecord(asArray(asRecord(result.indicators).quote)[0]).close,
      )
        .map(num)
        .filter((v): v is number => typeof v === 'number' && Number.isFinite(v) && v > 0);
      const history = closes.length > 0 ? closes.slice(-48) : [previous, price];
      const changePct = previous > 0 ? (price - previous) / previous : 0;
      return {
        id: `yahoo-${symbol.replace(/[^a-z0-9]/gi, '').toLowerCase()}`,
        name,
        market: 'us',
        indexValue: price,
        changePct,
        turnover: 0,
        heat: Math.max(1, Math.min(99, 50 + changePct * 1200)),
        marketCap: 0,
        history,
        stocks: [],
      };
    } catch {
      return null;
    }
  }

  private async futuMarketDepth(market: string): Promise<MarketDepthResponse> {
    let client: FutuWebsocket | undefined;
    const sectors: MarketDepthSector[] = [];
    try {
      client = await this.connectFutu();
      for (const qotMarket of futuMarkets(market)) {
        const payload = await client.GetHeatMapData({
          c2s: { market: qotMarket, sortField: 1, ascend: false, count: 12, plateType: 0 },
        });
        const plates = asArray(asRecord(payload.s2c).plateDataList).slice(0, 12);
        for (const plateRow of plates) {
          const sector = await this.futuSectorFromPlate(client, market, asRecord(plateRow));
          if (sector) sectors.push(sector);
        }
      }
    } catch (error) {
      // Return whatever was collected; the UI treats an empty list as pending.
      this.logger.warn(`Futu market depth unavailable: ${errorMessage(error)}`);
    } finally {
      if (client) closeFutu(client);
    }
    return { source: 'futu', market, delayed: false, sectors, updatedAt: Date.now() };
  }

  private async futuSectorFromPlate(
    client: FutuWebsocket,
    market: string,
    row: Record<string, unknown>,
  ): Promise<MarketDepthSector | null> {
    const plate = asRecord(row.plate);
    const code = str(plate.code);
    const qotMarket = num(plate.market);
    const indexValue = num(row.curPrice) ?? 0;
    if (!code || typeof qotMarket !== 'number') return null;
    const name = str(row.plateName) ?? code;
    const id = `futu-${qotMarket}-${code}`;
    const stocks = await this.futuPlateStocks(client, { market: qotMarket, code }, id);
    const changePct = (num(row.changeRate) ?? 0) / 100;
    const history = buildFlatHistory(indexValue, changePct);
    return {
      id,
      name,
      market,
      indexValue,
      changePct,
      turnover: num(row.turnover) ?? 0,
      heat: num(row.marketVal) ? Math.min(99, Math.max(10, Math.abs(changePct) * 1800 + 45)) : 50,
      marketCap: num(row.marketVal) ?? 0,
      history,
      stocks,
    };
  }

  private async futuPlateStocks(
    client: FutuWebsocket,
    plate: { market: number; code: string },
    sectorId: string,
  ): Promise<MarketDepthStock[]> {
    try {
      const listed = await client.GetPlateSecurity({
        c2s: { plate, sortField: 4, ascend: false },
      });
      const staticRows = asArray(asRecord(listed.s2c).staticInfoList).slice(0, 20);
      const securities = staticRows
        .map((item) => asRecord(asRecord(item).basic))
        .map((basic) => ({
          name: str(basic.name),
          security: asRecord(basic.security),
        }))
        .filter((row) => typeof row.security.market === 'number' && typeof row.security.code === 'string');
      if (securities.length === 0) return [];
      const quotes = await client.GetBasicQot({
        c2s: { securityList: securities.map((s) => s.security) },
      });
      const quoteRows = asArray(asRecord(quotes.s2c).basicQotList);
      return quoteRows
        .map((quote) => {
          const q = asRecord(quote);
          const security = asRecord(q.security);
          const code = str(security.code);
          const qotMarket = num(security.market);
          if (!code || typeof qotMarket !== 'number') return null;
          const symbol = `${marketPrefix(qotMarket)}.${code}`;
          const price = num(q.curPrice) ?? 0;
          return {
            id: `${sectorId}-${symbol}`,
            symbol,
            name: str(q.name) ?? symbol,
            sectorId,
            price,
            changePct: (num(q.changeRate) ?? 0) / 100,
            turnover: num(q.turnover) ?? 0,
            volume: num(q.hpVolume) ?? num(q.volume) ?? 0,
          };
        })
        .filter((stock): stock is MarketDepthStock => !!stock && stock.price > 0)
        .sort((a, b) => b.changePct - a.changePct)
        .slice(0, 12);
    } catch {
      return [];
    }
  }

  private connectFutu(): Promise<FutuWebsocket> {
    const host = process.env.FUTU_OPEND_HOST ?? 'futu-opend';
    const port = Number(process.env.FUTU_OPEND_PORT ?? 33333);
    const ssl = /^(true|1|yes|on)$/i.test(process.env.FUTU_OPEND_SSL ?? '');
    const key = process.env.FUTU_OPEND_KEY;
    return new Promise((resolve, reject) => {
      const client = new FutuWebsocket();
      const timer = setTimeout(() => {
        closeFutu(client);
        reject(new Error('futu websocket login timeout'));
      }, 8000);
      client.onlogin = (ok, msg) => {
        clearTimeout(timer);
        if (ok) resolve(client);
        else {
          closeFutu(client);
          reject(new Error(`futu websocket login failed: ${JSON.stringify(msg)}`));
        }
      };
      client.start(host, port, ssl, key);
    });
  }
}

function futuMarkets(market: string): number[] {
  if (market === 'hk') return [1];
  if (market === 'us') return [11];
  if (market === 'cn') return [21, 22];
  return [];
}

function marketPrefix(market: number): string {
  if (market === 1) return 'HK';
  if (market === 11) return 'US';
  if (market === 21) return 'SH';
  if (market === 22) return 'SZ';
  return String(market);
}

function closeFutu(client: FutuWebsocket): void {
  client.stop();
  const raw = client as unknown as { websock?: { close?: () => void } };
  raw.websock?.close?.();
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' ? (value as Record<string, unknown>) : {};
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function num(value: unknown): number | undefined {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (value && typeof (value as { toNumber?: () => number }).toNumber === 'function') {
    const n = (value as { toNumber: () => number }).toNumber();
    return Number.isFinite(n) ? n : undefined;
  }
  return undefined;
}

function str(value: unknown): string | undefined {
  return typeof value === 'string' && value ? value : undefined;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function buildFlatHistory(price: number, changePct: number): number[] {
  if (price <= 0) return [];
  const start = price / (1 + changePct || 1);
  return Array.from({ length: 36 }, (_, i) => {
    const p = i / 35;
    return start + (price - start) * p;
  });
}
