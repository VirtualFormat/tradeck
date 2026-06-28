import type { MarketTick, NormalizedEvent } from '@tradeck/shared';
import { PollingConnector } from '../polling.connector';

/**
 * Pull-type connector for East Money (东方财富) public quote feed.
 *
 * Polls the batch endpoint `push2.eastmoney.com/api/qt/ulist.np/get` for every
 * configured secid and emits one MarketTick per instrument. `config.symbols`
 * are full secids (`{market}.{code}`, e.g. `1.600519` 茅台 / `116.00700` 腾讯 /
 * `105.AAPL`), so no market→secid derivation is needed. Network/parse failures
 * are isolated by PollingConnector (logged, retried next poll).
 *
 * This is an unofficial endpoint; fields can change. Verified reachable from the
 * container (unlike Binance) and returns A-share / HK / US in one request.
 */
export class EastmoneyConnector extends PollingConnector {
  protected get intervalMs(): number {
    return (this.config.options?.intervalMs as number) ?? 3000;
  }

  private get endpoint(): string {
    const secids = this.config.symbols.join(',');
    // fltt=2 → prices already in decimal yuan/usd (no /100); invt=2 → numeric.
    return (
      'https://push2.eastmoney.com/api/qt/ulist.np/get' +
      `?secids=${encodeURIComponent(secids)}` +
      '&fields=f2,f3,f5,f12,f13,f14&fltt=2&invt=2'
    );
  }

  protected async fetchOnce(): Promise<NormalizedEvent[]> {
    if (this.config.symbols.length === 0) return [];
    const res = await fetch(this.endpoint, {
      headers: {
        Referer: 'https://quote.eastmoney.com/',
        'User-Agent':
          'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36',
      },
      signal: AbortSignal.timeout(8000),
    });
    if (!res.ok) throw new Error(`eastmoney http ${res.status}`);
    const json = (await res.json()) as EastmoneyResponse;
    const diff = json?.data?.diff;
    if (!Array.isArray(diff)) return [];

    const now = Date.now();
    const out: NormalizedEvent[] = [];
    for (const row of diff) {
      // f2 = last price (decimal). Halted / no-data rows return '-' or 0 → skip.
      const price = typeof row.f2 === 'number' && row.f2 > 0 ? row.f2 : null;
      if (price === null || typeof row.f12 !== 'string' || row.f13 === undefined) continue;

      const tick: MarketTick = {
        source: this.config.id,
        symbol: `${row.f13}.${row.f12}`, // = secid, keeps snapshot keys stable
        ts: now,
        price,
        volume: typeof row.f5 === 'number' && row.f5 >= 0 ? row.f5 : undefined,
        // f3 = day change in percent (1.23 → 0.0123); '-' when unavailable
        changePct: typeof row.f3 === 'number' ? row.f3 / 100 : undefined,
        name: typeof row.f14 === 'string' ? row.f14 : undefined,
      };
      out.push({ kind: 'tick', payload: tick });
    }
    return out;
  }
}

interface EastmoneyRow {
  f2?: number | string; // last price
  f3?: number | string; // day change %
  f5?: number | string; // volume (手)
  f12?: string; // code
  f13?: number; // market (1=SH, 0=SZ, 116=HK, 105/106/107=US)
  f14?: string; // name
}

interface EastmoneyResponse {
  data?: { diff?: EastmoneyRow[] } | null;
}
