import { useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import type { Ticker } from '@tradeck/shared';
import type { Market } from './market';
import { Card } from './widgets/Card';
import { dedupeTickers, isIndex } from './tickerUtils';

function fmtPrice(value: number): string {
  return value.toLocaleString('en-US', { maximumFractionDigits: 2, minimumFractionDigits: 2 });
}

function fmtChange(value: number): string {
  const sign = value > 0 ? '+' : value < 0 ? '-' : '';
  return `${sign}${Math.abs(value).toLocaleString('en-US', { maximumFractionDigits: 2, minimumFractionDigits: 2 })}`;
}

function fmtPct(fraction: number): string {
  const sign = fraction > 0 ? '+' : '';
  return `${sign}${(fraction * 100).toFixed(2)}%`;
}

function fmtAmount(value: number | undefined): string | null {
  if (value == null || value <= 0) return null;
  // eastmoney f6 单位为元；统一换算成「亿」
  const yi = value / 1e8;
  if (yi >= 10000) return `${(yi / 10000).toFixed(2)}万亿`;
  if (yi >= 1) return `${yi.toLocaleString('en-US', { maximumFractionDigits: 2 })}亿`;
  return `${value.toLocaleString('en-US')}`;
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
      className="pointer-events-none absolute bottom-0 right-0 h-8 w-[72%] opacity-40"
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
  '0.399001': '深证成指',
  '0.399006': '创业板指',
  '1.000688': '科创50',
  '1.000300': '沪深300',
  '1.000016': '上证50',
  '1.000905': '中证500',
  '100.HSI': '恒生指数',
  '100.HSTECH': '恒生科技',
  '^GSPC': '标普500',
  '^IXIC': '纳斯达克',
  '^DJI': '道琼斯',
};

/** 指数 symbol → 市场标签 */
const INDEX_MARKET: Record<string, string> = {
  '1.000001': 'A股',
  '0.399001': 'A股',
  '0.399006': 'A股',
  '1.000688': 'A股',
  '1.000300': 'A股',
  '1.000016': 'A股',
  '1.000905': 'A股',
  '100.HSI': '港股',
  '100.HSTECH': '港股',
  '^GSPC': '美股',
  '^IXIC': '美股',
  '^DJI': '美股',
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
  const sparkData = ticker.spark.length >= 2 ? ticker.spark : [ticker.price * (1 - ticker.changePct), ticker.price];
  const amountLabel = fmtAmount(ticker.amount);
  const hasOHLC = ticker.open != null || ticker.high != null || ticker.low != null || ticker.prevClose != null;

  return (
    <button
      type="button"
      onClick={onClick}
      className={`relative min-w-[208px] flex-1 overflow-hidden rounded-md border border-border bg-panel-2 px-3 py-2 text-left transition-colors hover:border-accent/70 ${
        flash === 'up' ? 'bg-up/10' : flash === 'down' ? 'bg-down/10' : ''
      }`}
    >
      <Sparkline data={sparkData} up={up} />
      <div className="relative z-10 flex h-full min-h-[124px] flex-col gap-1.5">
        {/* 顶部：市场标签 + 名称 + 涨跌箭头 + 振幅 */}
        <div className="flex items-center justify-between gap-2">
          <div className="flex min-w-0 items-center gap-1.5">
            <span className="shrink-0 rounded-sm bg-border/60 px-1 text-[9px] uppercase tracking-[0.14em] text-muted">
              {marketLabel}
            </span>
            <span className="truncate text-[12px] font-medium leading-none text-fg-dim">{name}</span>
          </div>
          <div className={`flex shrink-0 items-center gap-0.5 text-[10px] tab-nums ${up ? 'text-up' : 'text-down'}`}>
            <span>{up ? '▲' : '▼'}</span>
            {ticker.amplitude != null && (
              <span className="text-muted">
                <span className="text-[9px]">振</span>
                {(ticker.amplitude * 100).toFixed(2)}%
              </span>
            )}
          </div>
        </div>

        {/* 中部：大字价格 + 涨跌额 */}
        <div className="flex items-baseline gap-2">
          <span className={`tab-nums text-[20px] font-semibold leading-none ${up ? 'text-up' : 'text-down'}`}>
            {fmtPrice(ticker.price)}
          </span>
          {ticker.change != null && (
            <span className={`tab-nums text-[12px] leading-none ${up ? 'text-up' : 'text-down'}`}>
              {fmtChange(ticker.change)}
            </span>
          )}
        </div>

        {/* 涨跌幅 + 成交额 */}
        <div className="flex items-center justify-between gap-2">
          <span className={`tab-nums text-[11px] font-medium leading-none ${up ? 'text-up' : 'text-down'}`}>
            {fmtPct(ticker.changePct)}
          </span>
          {amountLabel && (
            <span className="truncate text-[10px] tab-nums leading-none text-muted">
              <span className="text-[9px]">额</span>
              {amountLabel}
            </span>
          )}
        </div>

        {/* 底部：开 / 高 / 低 / 昨收 */}
        {hasOHLC && (
          <div className="mt-auto grid grid-cols-2 gap-x-2 gap-y-0.5 border-t border-border/50 pt-1 text-[10px] tab-nums leading-tight text-muted">
            <div className="flex justify-between">
              <span className="text-[9px] text-muted">开</span>
              <span className="text-fg-dim">{ticker.open != null ? fmtPrice(ticker.open) : '—'}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-[9px] text-muted">高</span>
              <span className="text-fg-dim">{ticker.high != null ? fmtPrice(ticker.high) : '—'}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-[9px] text-muted">低</span>
              <span className="text-fg-dim">{ticker.low != null ? fmtPrice(ticker.low) : '—'}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-[9px] text-muted">昨</span>
              <span className="text-fg-dim">{ticker.prevClose != null ? fmtPrice(ticker.prevClose) : '—'}</span>
            </div>
          </div>
        )}
      </div>
    </button>
  );
}

function PopupSparkline({ data, up }: { data: number[]; up: boolean }): JSX.Element | null {
  if (data.length < 2) return null;
  const width = 420;
  const height = 110;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const span = max - min || 1;
  const points = data
    .map((v, i) => {
      const x = (i / (data.length - 1)) * width;
      const y = height - ((v - min) / span) * (height - 4) - 2;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(' ');
  return (
    <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" className="h-full w-full" aria-hidden>
      <polyline
        points={points}
        fill="none"
        stroke={up ? 'var(--color-up)' : 'var(--color-down)'}
        strokeWidth="2"
        strokeLinejoin="round"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
}

function IndexDetailPopup({ ticker, onClose }: { ticker: Ticker; onClose: () => void }): JSX.Element {
  const up = ticker.changePct >= 0;
  const name = ticker.name ?? INDEX_NAMES[ticker.symbol] ?? ticker.symbol;
  const marketLabel = INDEX_MARKET[ticker.symbol] ?? '';
  const sparkData = ticker.spark.length >= 2 ? ticker.spark : [ticker.price * (1 - ticker.changePct), ticker.price];

  const rows: { label: string; value: string | null; accent?: boolean }[] = [
    { label: '最新', value: fmtPrice(ticker.price), accent: true },
    { label: '涨跌额', value: ticker.change != null ? fmtChange(ticker.change) : null },
    { label: '涨跌幅', value: fmtPct(ticker.changePct) },
    { label: '振幅', value: ticker.amplitude != null ? `${(ticker.amplitude * 100).toFixed(2)}%` : null },
    { label: '今开', value: ticker.open != null ? fmtPrice(ticker.open) : null },
    { label: '最高', value: ticker.high != null ? fmtPrice(ticker.high) : null },
    { label: '最低', value: ticker.low != null ? fmtPrice(ticker.low) : null },
    { label: '昨收', value: ticker.prevClose != null ? fmtPrice(ticker.prevClose) : null },
    { label: '成交额', value: fmtAmount(ticker.amount) },
  ];

  // 用 createPortal 渲染到 document.body，逃离 react-grid-layout 的 transform 产生的 stacking context，
  // 否则 z-50 会被同层级的其他 grid item 盖住。
  return createPortal(
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/60" onClick={onClose}>
      <div
        className="w-[460px] rounded-lg border border-border bg-panel p-4 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-3 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="rounded-sm bg-border/60 px-1.5 py-0.5 text-[10px] uppercase tracking-[0.14em] text-muted">
              {marketLabel}
            </span>
            <span className="text-sm font-medium text-fg">{name}</span>
          </div>
          <button onClick={onClose} className="text-muted hover:text-fg">✕</button>
        </div>
        <div className="mb-3 flex items-baseline gap-3">
          <span className={`tab-nums text-2xl font-semibold ${up ? 'text-up' : 'text-down'}`}>
            {fmtPrice(ticker.price)}
          </span>
          <span className={`tab-nums text-sm ${up ? 'text-up' : 'text-down'}`}>
            {ticker.change != null ? fmtChange(ticker.change) : ''} ({fmtPct(ticker.changePct)})
          </span>
        </div>
        <div className="relative mb-3 h-[120px] overflow-hidden rounded-md bg-panel-2/50 p-1">
          <PopupSparkline data={sparkData} up={up} />
        </div>
        <div className="grid grid-cols-3 gap-x-4 gap-y-1.5 text-xs">
          {rows
            .filter((r) => r.value != null)
            .map((r) => (
              <div key={r.label} className="flex items-center justify-between gap-2 border-b border-border/40 pb-1">
                <span className="text-[10px] text-muted">{r.label}</span>
                <span className={`tab-nums ${r.accent ? (up ? 'text-up' : 'text-down') : 'text-fg-dim'}`}>
                  {r.value}
                </span>
              </div>
            ))}
        </div>
      </div>
    </div>,
    document.body,
  );
}

export function MarketOverview({ tickers, market }: { tickers: Ticker[]; market: Market }): JSX.Element {
  const [popupSymbol, setPopupSymbol] = useState<string | null>(null);
  // 按市场顺序固定排序：A股大盘 → 港股 → 美股
  const MARKET_ORDER: Record<string, number> = { cn: 0, hk: 1, us: 2 };
  const INDEX_SYMBOL_ORDER = [
    '1.000001', '0.399001', '0.399006', '1.000688', '1.000300', '1.000016', '1.000905',
    '100.HSI', '100.HSTECH',
    '^GSPC', '^IXIC', '^DJI',
  ];
  const indices = useMemo(() => {
    const list = dedupeTickers(tickers).filter(isIndex);
    const bySymbol = new Map(list.map((t) => [t.symbol, t]));
    // 按 INDEX_SYMBOL_ORDER 排序，未在列表中的排到末尾
    return INDEX_SYMBOL_ORDER
      .map((s) => bySymbol.get(s))
      .filter((t): t is Ticker => !!t)
      .concat(list.filter((t) => !INDEX_SYMBOL_ORDER.includes(t.symbol)))
      .sort((a, b) => {
        const ma = MARKET_ORDER[a.market ?? ''] ?? 9;
        const mb = MARKET_ORDER[b.market ?? ''] ?? 9;
        return ma - mb;
      });
  }, [tickers]);
  // 按 market tab 过滤：cn → A股大盘7只，hk → 恒生+恒生科技，us → 标普/纳指/道指
  const visibleIndices = useMemo(
    () => indices.filter((t) => t.market === market),
    [indices, market],
  );
  // popup 查找用完整列表，避免切换 market 后 popupTicker 丢失
  const popupTicker = useMemo(
    () => indices.find((t) => t.symbol === popupSymbol) ?? null,
    [indices, popupSymbol],
  );

  return (
    <Card title="大盘指数" subtitle="Market indices · global" corner="点击看走势">
      {visibleIndices.length > 0 ? (
        <div className="scroll-thin grid h-full min-h-0 grid-flow-col auto-cols-[minmax(208px,1fr)] gap-2 overflow-x-auto">
          {visibleIndices.map((ticker) => (
            <IndexTile
              key={ticker.symbol}
              ticker={ticker}
              onClick={() => setPopupSymbol(ticker.symbol)}
            />
          ))}
        </div>
      ) : (
        <div className="flex h-full items-center justify-center text-xs text-muted">
          等待{market === 'cn' ? 'A股' : market === 'hk' ? '港股' : '美股'}指数数据...
        </div>
      )}
      {popupTicker && <IndexDetailPopup ticker={popupTicker} onClose={() => setPopupSymbol(null)} />}
    </Card>
  );
}
