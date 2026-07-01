import { Hono } from 'hono';
import { cors } from 'hono/cors';
import type {
  DashboardLayout,
  DataSourceWithHealth,
  FeedItem,
  MarketDepthResponse,
  OhlcvInterval,
  Ticker,
} from '@tradeck/shared';
import { fetchEastmoneyTickers } from './connectors/eastmoney.js';
import { mockTickers } from './connectors/mock-tickers.js';
import { mockOhlcv } from './connectors/mock-ohlcv.js';
import { fetchRss } from './connectors/rss.js';

const app = new Hono();

// 开发期允许 vite 前端跨域访问本 Worker。
app.use('/api/*', cors());

const CACHE_SHORT = 'public, max-age=5, s-maxage=15';
const CACHE_FEED = 'public, max-age=30, s-maxage=120';

// ─── 固定配置（MVP 无 DB / 无个性化）──────────────────────────────

const DEFAULT_LAYOUT: DashboardLayout = {
  items: [
    { i: 'overview', x: 0, y: 0, w: 12, h: 3, minW: 6, minH: 3 },
    { i: 'price', x: 0, y: 3, w: 7, h: 8, minW: 4, minH: 6 },
    { i: 'movers', x: 7, y: 3, w: 5, h: 8, minW: 3, minH: 6 },
    { i: 'heat', x: 0, y: 11, w: 6, h: 8, minW: 4, minH: 6 },
    { i: 'sectorVolume', x: 6, y: 11, w: 6, h: 8, minW: 4, minH: 6 },
    { i: 'graph', x: 0, y: 19, w: 7, h: 7, minW: 4, minH: 5 },
    { i: 'feed', x: 7, y: 19, w: 5, h: 7, minW: 3, minH: 5 },
  ],
};

const FIXED_DATASOURCES: DataSourceWithHealth[] = [
  {
    id: 'eastmoney-cn',
    type: 'eastmoney',
    name: '东方财富 A股',
    enabled: true,
    config: { symbols: ['1.000001', '1.600519', '0.300750', '0.000858', '1.601318'] },
    createdAt: 0,
    updatedAt: 0,
    status: 'running',
  },
  {
    id: 'eastmoney-hk',
    type: 'eastmoney',
    name: '东方财富 港股',
    enabled: true,
    config: { symbols: ['116.00700', '116.09988', '116.03690', '100.HSI'] },
    createdAt: 0,
    updatedAt: 0,
    status: 'running',
  },
  {
    id: 'eastmoney-us',
    type: 'eastmoney',
    name: '东方财富 美股',
    enabled: true,
    config: { symbols: ['105.AAPL', '105.TSLA', '105.NVDA', '105.MSFT', '105.AMZN'] },
    createdAt: 0,
    updatedAt: 0,
    status: 'running',
  },
  {
    id: 'mock',
    type: 'mock',
    name: 'Mock 兜底',
    enabled: true,
    config: { symbols: [] },
    createdAt: 0,
    updatedAt: 0,
    status: 'running',
  },
  {
    id: 'rss',
    type: 'rss',
    name: '资讯 RSS',
    enabled: true,
    config: { symbols: [] },
    createdAt: 0,
    updatedAt: 0,
    status: 'running',
  },
];

const RSS_FEEDS: { url: string; source: string }[] = [
  { url: 'https://www.cnbc.com/id/100003114/device/rss/rss.html', source: 'CNBC' },
  { url: 'https://feeds.a.dj.com/rss/RSSMarketsMain.xml', source: 'WSJ Markets' },
];

// ─── 路由 ──────────────────────────────────────────────────────────

app.get('/', (c) => c.text('Tradeck API (Hono on Workers)'));

app.get('/api/health', (c) => c.json({ ok: true, ts: Date.now() }));

/** GET /api/tickers — 东方财富现拉 + Mock 兜底 */
app.get('/api/tickers', async (c) => {
  let tickers: Ticker[];
  try {
    const live = await fetchEastmoneyTickers();
    tickers = live.length > 0 ? [...live, ...mockTickers()] : mockTickers();
  } catch (err) {
    console.error('eastmoney failed, mock fallback:', err);
    tickers = mockTickers();
  }
  tickers.sort((a, b) => b.changePct - a.changePct);
  c.header('Cache-Control', CACHE_SHORT);
  return c.json(tickers);
});

/** GET /api/ohlcv?symbol=&interval=&limit= — Mock 生成（Yahoo 本地被封） */
app.get('/api/ohlcv', (c) => {
  const symbol = c.req.query('symbol') ?? 'MOCKUSDT';
  const interval = (c.req.query('interval') ?? '1m') as OhlcvInterval;
  const limit = Math.min(Number(c.req.query('limit') ?? 500), 1000);
  const bars = mockOhlcv(symbol, interval, limit);
  c.header('Cache-Control', CACHE_SHORT);
  return c.json(bars);
});

/** GET /api/market-depth?source=&market= — 前端默认用 mock，这里返回空 sectors */
app.get('/api/market-depth', (c) => {
  const source = c.req.query('source') ?? 'mock';
  const market = c.req.query('market') ?? 'cn';
  const body: MarketDepthResponse = {
    source,
    market,
    delayed: false,
    sectors: [],
    updatedAt: Date.now(),
  };
  c.header('Cache-Control', CACHE_SHORT);
  return c.json(body);
});

/** GET /api/feed?limit= — RSS 聚合 */
app.get('/api/feed', async (c) => {
  const limit = Math.min(Number(c.req.query('limit') ?? 30), 100);
  const results = await Promise.allSettled(RSS_FEEDS.map((f) => fetchRss(f.url, f.source)));
  const items = results
    .filter((r): r is PromiseFulfilledResult<FeedItem[]> => r.status === 'fulfilled')
    .flatMap((r) => r.value)
    .sort((a, b) => (b.publishedAt ?? 0) - (a.publishedAt ?? 0))
    .slice(0, limit);
  c.header('Cache-Control', CACHE_FEED);
  return c.json(items);
});

/** GET /api/datasources — 固定列表 */
app.get('/api/datasources', (c) => {
  c.header('Cache-Control', CACHE_SHORT);
  return c.json(FIXED_DATASOURCES);
});

/** POST /api/datasources — serverless 无状态，返回固定（no-op） */
app.post('/api/datasources', (c) => c.json({ error: 'serverless mode: datasource CRUD disabled' }, 405));
app.patch('/api/datasources/:id', (c) => c.json({ error: 'serverless mode: datasource CRUD disabled' }, 405));
app.delete('/api/datasources/:id', (c) => c.json({ error: 'serverless mode: datasource CRUD disabled' }, 405));

/** GET /api/dashboard/layout — 固定布局 */
app.get('/api/dashboard/layout', (c) => {
  c.header('Cache-Control', CACHE_SHORT);
  return c.json(DEFAULT_LAYOUT);
});

/** PUT /api/dashboard/layout — serverless 无状态，回传传入布局（no-op 持久化） */
app.put('/api/dashboard/layout', async (c) => {
  const body = await c.req.json<DashboardLayout>().catch(() => DEFAULT_LAYOUT);
  return c.json(body);
});

export default app;
