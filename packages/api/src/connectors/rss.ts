import { XMLParser } from 'fast-xml-parser';
import type { FeedItem } from '@tradeck/shared';

/**
 * RSS 连接器（Pull 型）。服务端拉 XML → 解析 → 归一化 FeedItem[]。
 * 前端不能直连（CORS + XML），必须经这里。
 */

const UA =
  'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36';

const parser = new XMLParser({ ignoreAttributes: false, attributeNamePrefix: '@_' });

interface RssRawItem {
  title?: string;
  link?: string;
  description?: string;
  pubDate?: string;
  guid?: string | { '#text'?: string };
}

export async function fetchRss(url: string, source: string): Promise<FeedItem[]> {
  const res = await fetch(url, { headers: { 'User-Agent': UA } });
  if (!res.ok) throw new Error(`RSS HTTP ${res.status}`);
  const xml = await res.text();
  const doc = parser.parse(xml) as {
    rss?: { channel?: { item?: RssRawItem | RssRawItem[] } };
  };
  const raw = doc.rss?.channel?.item;
  const items = Array.isArray(raw) ? raw : raw ? [raw] : [];
  return items.map((it) => normalizeItem(it, source)).filter((i): i is FeedItem => i !== null);
}

function normalizeItem(it: RssRawItem, source: string): FeedItem | null {
  const title = it.title?.trim();
  const link = it.link?.trim();
  if (!title || !link) return null;
  const guid = typeof it.guid === 'string' ? it.guid : it.guid?.['#text'];
  const publishedAt = it.pubDate ? Date.parse(it.pubDate) : undefined;
  return {
    source,
    id: `${source}:${guid ?? link}`,
    title,
    url: link,
    summary: it.description ? stripHtml(it.description).slice(0, 200) : undefined,
    publishedAt: Number.isNaN(publishedAt) ? undefined : publishedAt,
  };
}

function stripHtml(s: string): string {
  return s.replace(/<[^>]*>/g, '').replace(/\s+/g, ' ').trim();
}
