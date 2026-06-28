// Placeholder data for the dashboard layout. Only the candle chart is wired to
// real data; everything here is static mock for the visual shell.

/** Symbols with a live mock data source in this environment. */
export const LIVE_SYMBOLS = ['MOCKUSDT', 'MOCKETH', 'MOCKSOL'] as const;
export const LIVE_SYMBOL = LIVE_SYMBOLS[0];

export interface RecentWin {
  symbol: string;
  label: string;
  amount: number;
}

export interface PnlMock {
  pnl: number;
  realized: number;
  trades: number;
  winRate: number;
  sharpe: number;
  recentWins: RecentWin[];
}

export const pnlMock: PnlMock = {
  pnl: 385545,
  realized: 401819,
  trades: 5944,
  winRate: 0.71,
  sharpe: 4.21,
  recentWins: [
    { symbol: 'ETH 2.8K', label: 'APR', amount: 31423 },
    { symbol: 'XRP UP', label: 'APR 9', amount: 29247 },
    { symbol: 'BTC 80K', label: 'JUN', amount: 28062 },
    { symbol: 'ETH 2.4K', label: 'APR', amount: 14276 },
  ],
};

export interface TopWinMock {
  multiple: number;
  entry: number;
  payout: number;
}

export const topWinMock: TopWinMock = {
  multiple: 11.38,
  entry: 3029,
  payout: 34452,
};

export interface MetricItem {
  label: string;
  value: string;
  tone?: 'up' | 'down' | 'neutral';
}

export const latticeMetrics: MetricItem[] = [
  { label: 'BALLS DROPPED', value: '5,944' },
  { label: 'LANDED GREEN', value: '100.0%', tone: 'up' },
  { label: 'EV / TRADE', value: '+$118', tone: 'up' },
  { label: 'SESSION PNL', value: '+$236', tone: 'up' },
  { label: 'ALL-TIME', value: '5,944' },
  { label: 'REALIZED', value: '+$401,819', tone: 'up' },
];

export const ridgeMetrics: MetricItem[] = [
  { label: 'SESSIONS', value: '1,284' },
  { label: 'TAIL MASS', value: '0.21%' },
  { label: 'IMPLIED VOL', value: '×478.2' },
  { label: 'AVG ENTRY', value: '1.2¢' },
  { label: 'BEST HIT', value: '×81.2', tone: 'up' },
  { label: 'REALIZED', value: '+$401,819', tone: 'up' },
];

export interface LatticeMock {
  bars: number[];
}

export const latticeMock: LatticeMock = {
  // bell-ish heights (0..1)
  bars: [0.08, 0.18, 0.34, 0.55, 0.78, 0.95, 0.82, 0.58, 0.36, 0.2, 0.1],
};

export interface RidgeCurve {
  peakX: number; // 0..1 peak position
  amp: number; // 0..1 amplitude
  baseY: number; // vertical offset (px in viewBox)
  opacity: number;
}

export const ridgeCurves: RidgeCurve[] = Array.from({ length: 9 }, (_, i) => ({
  peakX: 0.5 + (Math.sin(i * 0.7) * 0.12),
  amp: 0.9 - i * 0.04,
  baseY: 30 + i * 16,
  opacity: 1 - i * 0.09,
}));

export interface GraphNode {
  id: string;
  x: number;
  y: number;
  r: number;
  kind: 'up' | 'down' | 'neu' | 'hub';
}
export interface GraphEdge {
  from: string;
  to: string;
}

export interface GraphMock {
  legend: string[];
  nodes: GraphNode[];
  edges: GraphEdge[];
  pUp: number;
  pDown: number;
  confidence: number;
  bars: number[];
}

export const graphMock: GraphMock = {
  legend: ['Bear signal', 'Bull signal', 'Median path', 'Catalyst', 'Cluster hub'],
  nodes: [
    { id: 'BEAR_CLUSTER', x: 120, y: 90, r: 26, kind: 'down' },
    { id: 'HUB_PRIME', x: 300, y: 180, r: 30, kind: 'hub' },
    { id: 'CATALYST', x: 470, y: 100, r: 18, kind: 'neu' },
    { id: 'BULL', x: 560, y: 70, r: 14, kind: 'up' },
    { id: 'MIRO', x: 640, y: 120, r: 16, kind: 'up' },
    { id: 'n1', x: 200, y: 50, r: 6, kind: 'down' },
    { id: 'n2', x: 230, y: 140, r: 5, kind: 'down' },
    { id: 'n3', x: 380, y: 60, r: 6, kind: 'neu' },
    { id: 'n4', x: 400, y: 220, r: 7, kind: 'up' },
    { id: 'n5', x: 520, y: 200, r: 6, kind: 'up' },
    { id: 'n6', x: 90, y: 160, r: 5, kind: 'down' },
  ],
  edges: [
    { from: 'BEAR_CLUSTER', to: 'HUB_PRIME' },
    { from: 'HUB_PRIME', to: 'CATALYST' },
    { from: 'CATALYST', to: 'BULL' },
    { from: 'BULL', to: 'MIRO' },
    { from: 'BEAR_CLUSTER', to: 'n1' },
    { from: 'BEAR_CLUSTER', to: 'n2' },
    { from: 'HUB_PRIME', to: 'n3' },
    { from: 'HUB_PRIME', to: 'n4' },
    { from: 'CATALYST', to: 'n5' },
    { from: 'BEAR_CLUSTER', to: 'n6' },
  ],
  pUp: 0.76,
  pDown: 0.24,
  confidence: 0.942,
  bars: [0.2, 0.35, 0.28, 0.5, 0.42, 0.65, 0.58, 0.8, 0.72, 0.9],
};

export interface FooterMock {
  model: string;
  fills: number;
  backtest: string;
  latencyMs: number;
  round: number;
}

export const footerMock: FooterMock = {
  model: 'tradeck-core',
  fills: 5944,
  backtest: '41.6 GB',
  latencyMs: 12,
  round: 7165,
};
