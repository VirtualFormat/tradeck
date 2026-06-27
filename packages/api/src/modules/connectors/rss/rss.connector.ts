import type { FeedItem, NormalizedEvent } from '@tradeck/shared';
import { PollingConnector } from '../polling.connector';

/**
 * Pull-type connector for RSS feeds. Polls the feed URL, parses items with a
 * minimal hand-written parser (no XML dependency), and emits FeedItems.
 * Network failures are isolated by PollingConnector (logged, retried next poll).
 */
export class RssConnector extends PollingConnector {
  protected get intervalMs(): number {
    return (this.config.options?.intervalMs as number) ?? 60_000;
  }

  private get url(): string {
    return (
      (this.config.options?.url as string) ??
      'https://rss.sina.com.cn/roll/finance/hot_roll.xml'
    );
  }

  protected async fetchOnce(): Promise<NormalizedEvent[]> {
    const res = await fetch(this.url, { signal: AbortSignal.timeout(8000) });
    if (!res.ok) throw new Error(`rss http ${res.status}`);
    const xml = await res.text();
    return parseRssItems(xml).map((item) => {
      const evt: NormalizedEvent = {
        kind: 'feed',
        payload: { ...item, source: this.config.id },
      };
      return evt;
    });
  }
}

const ITEM_RE = /<item[\s\S]*?<\/item>/gi;
function tag(block: string, name: string): string | undefined {
  const m = new RegExp(`<${name}[^>]*>([\\s\\S]*?)</${name}>`, 'i').exec(block);
  if (!m) return undefined;
  return decode(m[1].replace(/<!\[CDATA\[([\s\S]*?)\]\]>/g, '$1').trim());
}

function decode(s: string): string {
  return s
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&amp;/g, '&')
    .replace(/<[^>]+>/g, '')
    .trim();
}

/** Minimal RSS item parser; tolerant of malformed entries (skips bad ones). */
export function parseRssItems(xml: string): Omit<FeedItem, 'source'>[] {
  const out: Omit<FeedItem, 'source'>[] = [];
  const blocks = xml.match(ITEM_RE) ?? [];
  for (const block of blocks) {
    try {
      const title = tag(block, 'title');
      const link = tag(block, 'link');
      if (!title || !link) continue;
      const pub = tag(block, 'pubDate');
      const ts = pub ? Date.parse(pub) : Date.now();
      out.push({
        id: tag(block, 'guid') ?? link,
        title,
        url: link,
        summary: tag(block, 'description'),
        publishedAt: Number.isNaN(ts) ? Date.now() : ts,
      });
    } catch {
      // skip malformed item
    }
  }
  return out;
}
