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
import { fetchQuotes, fetchChart } from './connectors/yahoo.js';
import { mockTickers } from './connectors/mock-tickers.js';
import { mockOhlcv } from './connectors/mock-ohlcv.js';
import { fetchRss } from './connectors/rss.js';

// ASSETS 绑定：Cloudflare Workers Static Assets（前端构建产物）。
interface Env {
  ASSETS: { fetch: (request: Request) => Promise<Response> };
  // ENVIRONMENT=production 时禁用 Mock，只用东方财富 + Yahoo。
  // 本地 dev 不设置或设为 dev，保留 Mock 兜底。
  ENVIRONMENT?: string;
}

const app = new Hono<{ Bindings: Env }>();

// 开发期允许 vite 前端跨域访问本 Worker（生产同域不需要，但无害）。
app.use('/api/*', cors());

const CACHE_SHORT = 'public, max-age=5, s-maxage=15';
const CACHE_FEED = 'public, max-age=30, s-maxage=120';

// 生产环境判断：ENVIRONMENT=production 时为 true。
const isProd = (c: { env: { ENVIRONMENT?: string } }) => c.env.ENVIRONMENT === 'production';

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
    id: 'yahoo',
    type: 'http-json',
    name: 'Yahoo Finance',
    enabled: true,
    config: { symbols: ['^GSPC', '^IXIC', '^DJI', 'AAPL', 'MSFT', 'NVDA', 'TSLA', 'AMZN', 'BTC-USD', 'ETH-USD'] },
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

// Yahoo Finance 关注列表（生产环境用，补充东方财富不覆盖的指数/美股）。
const YAHOO_SYMBOLS = [
  '^GSPC', '^IXIC', '^DJI',    // 美股指数
  'AAPL', 'MSFT', 'NVDA', 'TSLA', 'AMZN',  // 美股个股（MoversBar 用）
];

// 把 Yahoo MarketTick 转成 Ticker（前端 /api/tickers 期望的格式）。
function yahooTickToTicker(t: import('@tradeck/shared').MarketTick): Ticker {
  return {
    source: 'yahoo',
    symbol: t.symbol,
    price: t.price,
    volume: t.volume,
    ts: t.ts,
    changePct: t.changePct ?? 0,
    spark: [t.price * (1 - (t.changePct ?? 0)), t.price],
    name: t.name,
    market: 'us', // Yahoo 源主要是美股/指数/加密
    prevClose: t.prevClose,
    change: t.change,
  };
}

// ─── 路由 ──────────────────────────────────────────────────────────

app.get('/api/health', (c) => c.json({ ok: true, ts: Date.now() }));

/** GET /api/tickers — 生产: 东方财富+Yahoo; dev: 东方财富+Mock 兜底 */
app.get('/api/tickers', async (c) => {
  let tickers: Ticker[];
  if (isProd(c)) {
    // 生产：东方财富 + Yahoo，无 Mock
    const [emResult, yhResult] = await Promise.allSettled([
      fetchEastmoneyTickers(),
      fetchQuotes(YAHOO_SYMBOLS).then((ticks) => ticks.map(yahooTickToTicker)),
    ]);
    const em = emResult.status === 'fulfilled' ? emResult.value : [];
    const yh = yhResult.status === 'fulfilled' ? yhResult.value : [];
    tickers = [...em, ...yh];
    if (tickers.length === 0) {
      // 两个源都挂了，返回空（生产不留 Mock 兜底）
      console.error('prod: both eastmoney and yahoo failed');
    }
  } else {
    // dev：东方财富 + Mock 兜底
    try {
      const live = await fetchEastmoneyTickers();
      tickers = live.length > 0 ? [...live, ...mockTickers()] : mockTickers();
    } catch (err) {
      console.error('eastmoney failed, mock fallback:', err);
      tickers = mockTickers();
    }
  }
  tickers.sort((a, b) => b.changePct - a.changePct);
  c.header('Cache-Control', CACHE_SHORT);
  return c.json(tickers);
});

/** GET /api/ohlcv?symbol=&interval=&limit= — 生产: Yahoo chart; dev: Mock */
app.get('/api/ohlcv', async (c) => {
  const symbol = c.req.query('symbol') ?? 'AAPL';
  const interval = (c.req.query('interval') ?? '1m') as OhlcvInterval;
  const limit = Math.min(Number(c.req.query('limit') ?? 500), 1000);

  if (isProd(c)) {
    // 生产：Yahoo chart 现拉
    try {
      // Yahoo range 映射：1m→1d, 5m→5d, 15m→5d, 1h→1mo, 4h→3mo, 1d→1y
      const rangeMap: Record<OhlcvInterval, string> = {
        '1m': '1d', '5m': '5d', '15m': '5d', '1h': '1mo', '4h': '3mo', '1d': '1y',
      };
      const range = rangeMap[interval] ?? '1mo';
      const bars = await fetchChart(symbol, range, interval);
      c.header('Cache-Control', 'public, max-age=30, s-maxage=300');
      return c.json(bars);
    } catch (err) {
      console.error('yahoo chart failed:', err);
      return c.json({ error: 'chart fetch failed' }, 502);
    }
  }

  // dev：Mock 生成
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

/** GET /api/datasources — 固定列表（生产环境过滤掉 mock） */
app.get('/api/datasources', (c) => {
  const sources = isProd(c)
    ? FIXED_DATASOURCES.filter((s) => s.type !== 'mock')
    : FIXED_DATASOURCES;
  c.header('Cache-Control', CACHE_SHORT);
  return c.json(sources);
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

// SPA 兜底：非 /api 路径交给静态资源（前端构建产物）处理。
// 本地 dev 时 ASSETS 未绑定（dist 不存在），返回提示；生产部署后自动服务静态文件。
app.all('*', async (c) => {
  if (c.env.ASSETS) {
    return c.env.ASSETS.fetch(c.req.raw);
  }
  return c.text('API only. In dev, frontend runs on http://localhost:5173', 404);
});

export default app;
