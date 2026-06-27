import type { GenericMetric, MarketTick, NormalizedEvent } from '@tradeck/shared';
import { PollingConnector } from '../polling.connector';
import { jsonPath } from './json-path';

function num(v: unknown): number | undefined {
  if (typeof v === 'number') return v;
  if (typeof v === 'string' && v.trim() !== '' && !Number.isNaN(Number(v))) return Number(v);
  return undefined;
}

/**
 * Generic config-driven HTTP/JSON connector. Polls a URL and maps fields via
 * minimal JSONPath into MarketTick (output=tick) or GenericMetric(s)
 * (output=metric) — no code needed to onboard a new source.
 */
export class HttpJsonConnector extends PollingConnector {
  protected get intervalMs(): number {
    return (this.config.options?.intervalMs as number) ?? 5000;
  }

  protected async fetchOnce(): Promise<NormalizedEvent[]> {
    const opt = this.config.options ?? {};
    const url = opt.url as string | undefined;
    if (!url) throw new Error(`http-json ${this.config.id}: missing url`);

    const res = await fetch(url, { signal: AbortSignal.timeout(8000) });
    if (!res.ok) throw new Error(`http-json http ${res.status}`);
    const json: unknown = await res.json();

    const mapping = (opt.mapping as Record<string, string>) ?? {};
    const output = (opt.output as 'tick' | 'metric') ?? 'metric';

    if (output === 'tick') {
      const price = num(jsonPath(json, mapping.price));
      if (price === undefined) return [];
      const tick: MarketTick = {
        source: this.config.id,
        symbol: (opt.symbol as string) ?? 'UNKNOWN',
        ts: Date.now(),
        price,
        volume: num(jsonPath(json, mapping.volume)),
      };
      return [{ kind: 'tick', payload: tick }];
    }

    const out: NormalizedEvent[] = [];
    for (const [key, path] of Object.entries(mapping)) {
      const value = num(jsonPath(json, path));
      if (value === undefined) continue;
      const metric: GenericMetric = { source: this.config.id, key, ts: Date.now(), value };
      out.push({ kind: 'metric', payload: metric });
    }
    return out;
  }
}
