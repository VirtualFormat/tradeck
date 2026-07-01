import { useEffect, useMemo, useRef, useState } from 'react';
import type { Ticker } from '@tradeck/shared';
import { Card } from './widgets/Card';
import { dedupeTickers, isIndex } from './tickerUtils';

function fmtValue(value: number): string {
  return value.toLocaleString('en-US', { maximumFractionDigits: 2 });
}

function Sparkline({ data, up }: { data: number[]; up: boolean }): JSX.Element | null {
  if (data.length < 2) return null;
  const width = 120;
  const height = 30;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const span = max - min || 1;
  const points = data
    .map((v, i) => {
      const x = (i / (data.length - 1)) * width;
      const y = height - ((v - min) / span) * (height - 2) - 1;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(' ');

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      className="pointer-events-none absolute bottom-0 right-0 h-8 w-[72%] opacity-55"
      aria-hidden
    >
      <polyline
        points={points}
        fill="none"
        stroke={up ? 'var(--color-up)' : 'var(--color-down)'}
        strokeWidth="1.5"
        strokeLinejoin="round"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
}

/** 指数 symbol → 显示名（中文名） */
const INDEX_NAMES: Record<string, string> = {
  '1.000001': '上证指数',
  '100.HSI': '恒生指数',
  '^GSPC': '标普500',
  '^IXIC': '纳斯达克',
  '^DJI': '道琼斯',
  'BTC-USD': '比特币',
  'ETH-USD': '以太坊',
};

/** 指数 symbol → 市场标签 */
const INDEX_MARKET: Record<string, string> = {
  '1.000001': 'A股',
  '100.HSI': '港股',
  '^GSPC': '美股',
  '^IXIC': '美股',
  '^DJI': '美股',
  'BTC-USD': '加密',
  'ETH-USD': '加密',
};

function IndexTile({ ticker, onClick }: { ticker: Ticker; onClick: () => void }): JSX.Element {
  const previous = useRef(ticker.price);
  const [flash, setFlash] = useState<'up' | 'down' | null>(null);
  const up = ticker.changePct >= 0;

  useEffect(() => {
    if (ticker.price > previous.current) setFlash('up');
    if (ticker.price < previous.current) setFlash('down');
    previous.current = ticker.price;
    const timer = setTimeout(() => setFlash(null), 450);
    return () => clearTimeout(timer);
  }, [ticker.price]);

  const name = ticker.name ?? INDEX_NAMES[ticker.symbol] ?? ticker.symbol;
  const marketLabel = INDEX_MARKET[ticker.symbol] ?? '';

  return (
    <button
      type="button"
      onClick={onClick}
      className={`relative min-w-[154px] flex-1 overflow-hidden rounded-md border border-border bg-panel-2 px-2.5 py-2 text-left transition-colors hover:border-accent/70 ${
        flash === 'up' ? 'bg-up/10' : flash === 'down' ? 'bg-down/10' : ''
      }`}
    >
      <Sparkline data={ticker.spark.length >= 2 ? ticker.spark : [ticker.price * (1 - ticker.changePct), ticker.price]} up={up} />
      <div className="relative z-10 flex h-full min-h-[46px] flex-col justify-between">
        <div className="flex items-center justify-between gap-2">
          <span className="text-[9px] uppercase tracking-[0.16em] text-muted">{marketLabel}</span>
          <span className={`tab-nums text-[9px] ${up ? 'text-up' : 'text-down'}`}>
            {up ? '▲' : '▼'}
          </span>
        </div>
        <div className="truncate text-[11px] font-medium leading-none text-fg-dim">{name}</div>
        <div className="flex items-end justify-between gap-2">
          <span className={`tab-nums text-[15px] font-semibold leading-none ${up ? 'text-up' : 'text-down'}`}>
            {fmtValue(ticker.price)}
          </span>
          <span className={`tab-nums text-[10px] leading-none ${up ? 'text-up' : 'text-down'}`}>
            {up ? '+' : ''}
            {(ticker.changePct * 100).toFixed(2)}%
          </span>
        </div>
      </div>
    </button>
  );
}

export function MarketOverview({ tickers }: { tickers: Ticker[] }): JSX.Element {
  const [popupSymbol, setPopupSymbol] = useState<string | null>(null);
  const indices = useMemo(() => dedupeTickers(tickers).filter(isIndex), [tickers]);
  const popupTicker = useMemo(
    () => indices.find((t) => t.symbol === popupSymbol) ?? null,
    [indices, popupSymbol],
  );

  return (
    <Card title="指数总览" subtitle="Market indices · live" corner="点击看走势">
      {indices.length > 0 ? (
        <div className="scroll-thin grid h-full min-h-0 grid-flow-col auto-cols-[minmax(154px,1fr)] gap-2 overflow-x-auto">
          {indices.map((ticker) => (
            <IndexTile
              key={ticker.symbol}
              ticker={ticker}
              onClick={() => setPopupSymbol(ticker.symbol)}
            />
          ))}
        </div>
      ) : (
        <div className="flex h-full items-center justify-center text-xs text-muted">
          等待指数数据...
        </div>
      )}
      {popupTicker && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={() => setPopupSymbol(null)}>
          <div className="rounded-lg border border-border bg-panel p-4 w-[480px] h-[320px]" onClick={(e) => e.stopPropagation()}>
            <div className="mb-2 flex items-center justify-between">
              <span className="text-sm font-medium text-fg">
                {popupTicker.name ?? INDEX_NAMES[popupTicker.symbol] ?? popupTicker.symbol}
              </span>
              <button onClick={() => setPopupSymbol(null)} className="text-muted hover:text-fg">✕</button>
            </div>
            <div className="text-xs text-muted mb-2">
              {popupTicker.price.toLocaleString('en-US', { maximumFractionDigits: 2 })} ·{' '}
              <span className={popupTicker.changePct >= 0 ? 'text-up' : 'text-down'}>
                {popupTicker.changePct >= 0 ? '+' : ''}
                {(popupTicker.changePct * 100).toFixed(2)}%
              </span>
            </div>
            <div className="h-[240px]">
              <Sparkline data={popupTicker.spark.length >= 2 ? popupTicker.spark : [popupTicker.price]} up={popupTicker.changePct >= 0} />
            </div>
          </div>
        </div>
      )}
    </Card>
  );
}
