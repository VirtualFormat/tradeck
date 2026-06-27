import type { FeedItem, NormalizedEvent } from '@tradeck/shared';
import { BaseConnector } from '../base.connector';

const HEADLINES = [
  'BTC reclaims key level as ETF inflows accelerate',
  'ETH staking yield ticks higher amid validator queue',
  'Macro desk: rate-cut odds reprice risk assets',
  'On-chain: stablecoin supply hits local high',
  'Options skew flips bullish into monthly expiry',
  'Liquidity map shows thin order book above resistance',
  'Funding rates normalize after weekend volatility',
  'Altcoin rotation broadens as dominance dips',
];
const TAGS = [['BTC'], ['ETH'], ['MACRO'], ['ONCHAIN'], ['OPTIONS']];

/**
 * Mock feed connector: emits a synthetic finance headline on a timer so the
 * news stream always has content even when the real RSS source is unreachable.
 */
export class MockFeedConnector extends BaseConnector {
  private timer?: NodeJS.Timeout;
  private seq = 0;

  async start(): Promise<void> {
    this.setStatus('running');
    const intervalMs = (this.config.options?.intervalMs as number) ?? 8000;
    this.emitOne();
    this.timer = setInterval(() => this.emitOne(), intervalMs);
  }

  async stop(): Promise<void> {
    if (this.timer) clearInterval(this.timer);
    this.setStatus('stopped');
  }

  private emitOne(): void {
    const i = this.seq % HEADLINES.length;
    const item: FeedItem = {
      source: this.config.id,
      id: `mock-${Date.now()}-${this.seq}`,
      title: HEADLINES[i],
      url: 'https://example.com/news',
      summary: 'Synthetic headline for demo / fallback feed.',
      publishedAt: Date.now(),
      tags: TAGS[this.seq % TAGS.length],
    };
    this.seq += 1;
    const evt: NormalizedEvent = { kind: 'feed', payload: item };
    this.emit(evt);
  }
}
