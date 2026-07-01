/**
 * 关注列表 —— 当前阶段固定（无登录、无个性化）。
 * 将来个性化时改为从 localStorage / KV 读取。
 * symbol 用 Yahoo Finance 代码规范。
 */
export interface WatchItem {
  symbol: string;
  label: string;
}

export const DEFAULT_WATCHLIST: WatchItem[] = [
  { symbol: '^GSPC', label: '标普500' },
  { symbol: '^IXIC', label: '纳斯达克' },
  { symbol: '^DJI', label: '道琼斯' },
  { symbol: 'AAPL', label: '苹果' },
  { symbol: 'MSFT', label: '微软' },
  { symbol: 'NVDA', label: '英伟达' },
  { symbol: 'TSLA', label: '特斯拉' },
  { symbol: 'BTC-USD', label: '比特币' },
  { symbol: 'ETH-USD', label: '以太坊' },
  { symbol: '000001.SS', label: '上证指数' },
];

/**
 * 默认 RSS 资讯源（已实测可用，2026-07-01）。
 * 原新浪财经占位源已死（停更 2018、零条），故换成 CNBC + WSJ Markets。可随时增删。
 */
export const DEFAULT_RSS_FEEDS: { url: string; source: string }[] = [
  { url: 'https://www.cnbc.com/id/100003114/device/rss/rss.html', source: 'CNBC' },
  { url: 'https://feeds.a.dj.com/rss/RSSMarketsMain.xml', source: 'WSJ Markets' },
];
