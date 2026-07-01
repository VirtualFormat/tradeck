import { Hono } from 'hono';
import { cors } from 'hono/cors';
import {
  DEFAULT_WATCHLIST,
  DEFAULT_RSS_FEEDS,
  type FeedResponse,
  type QuoteResponse,
} from '@tradeck/shared';
import { fetchQuotes, fetchChart } from './connectors/yahoo.js';
import { mockQuotes } from './connectors/mock.js';
import { fetchRss } from './connectors/rss.js';

const app = new Hono();

// 开发期允许 vite 前端跨域访问本 Worker（生产同域可去掉）。
app.use('/api/*', cors());

// 边缘缓存：多人同时看只穿透上游一次。
const CACHE_HEADER = 'public, max-age=5, s-maxage=30';

app.get('/', (c) => c.text('Tradeck API (Hono on Workers) — see /api/*'));

app.get('/api/health', (c) => c.json({ ok: true, ts: Date.now() }));

/** 最新报价：Yahoo 拉取，失败降级 Mock */
app.get('/api/quote', async (c) => {
  const symbolsParam = c.req.query('symbols');
  const symbols = symbolsParam
    ? symbolsParam.split(',').map((s) => s.trim()).filter(Boolean)
    : DEFAULT_WATCHLIST.map((w) => w.symbol);

  let ticks;
  try {
    ticks = await fetchQuotes(symbols);
    if (ticks.length === 0) ticks = mockQuotes(symbols);
  } catch (err) {
    console.error('yahoo quote failed, fallback to mock:', err);
    ticks = mockQuotes(symbols);
  }

  const body: QuoteResponse = { ticks, fetchedAt: Date.now() };
  c.header('Cache-Control', CACHE_HEADER);
  return c.json(body);
});

/** 历史 K 线（历史面板用） */
app.get('/api/chart', async (c) => {
  const symbol = c.req.query('symbol');
  if (!symbol) return c.json({ error: 'symbol required' }, 400);
  const range = c.req.query('range') ?? '1mo';
  const interval = c.req.query('interval') ?? '1d';
  try {
    const bars = await fetchChart(symbol, range, interval);
    c.header('Cache-Control', 'public, max-age=30, s-maxage=300');
    return c.json({ symbol, interval, bars, fetchedAt: Date.now() });
  } catch (err) {
    console.error('yahoo chart failed:', err);
    return c.json({ error: 'chart fetch failed' }, 502);
  }
});

/** 资讯流：聚合 RSS */
app.get('/api/feed', async (c) => {
  const results = await Promise.allSettled(
    DEFAULT_RSS_FEEDS.map((f) => fetchRss(f.url, f.source)),
  );
  const items = results
    .filter((r): r is PromiseFulfilledResult<Awaited<ReturnType<typeof fetchRss>>> => r.status === 'fulfilled')
    .flatMap((r) => r.value)
    .sort((a, b) => (b.publishedAt ?? 0) - (a.publishedAt ?? 0))
    .slice(0, 50);

  const body: FeedResponse = { items, fetchedAt: Date.now() };
  c.header('Cache-Control', CACHE_HEADER);
  return c.json(body);
});

export default app;
