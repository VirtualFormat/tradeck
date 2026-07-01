import { useEffect, useMemo, useRef, useState } from 'react';
import type { EChartsOption } from 'echarts';
import type { MarketDepthSector } from '@tradeck/shared';
import { Card } from './widgets/Card';
import { Popup } from './widgets/Popup';
import { useEChart } from '../charts/useEChart';
import { MARKET_LABEL, type DataSourceMode, type Market } from './market';

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

function IndexTile({
  sector,
  market,
  onClick,
}: {
  sector: MarketDepthSector;
  market: Market;
  onClick: () => void;
}): JSX.Element {
  const previous = useRef(sector.indexValue);
  const [flash, setFlash] = useState<'up' | 'down' | null>(null);
  const up = sector.changePct >= 0;

  useEffect(() => {
    if (sector.indexValue > previous.current) setFlash('up');
    if (sector.indexValue < previous.current) setFlash('down');
    previous.current = sector.indexValue;
    const timer = setTimeout(() => setFlash(null), 450);
    return () => clearTimeout(timer);
  }, [sector.indexValue]);

  return (
    <button
      type="button"
      onClick={onClick}
      className={`relative min-w-[154px] flex-1 overflow-hidden rounded-md border border-border bg-panel-2 px-2.5 py-2 text-left transition-colors hover:border-accent/70 ${
        flash === 'up' ? 'bg-up/10' : flash === 'down' ? 'bg-down/10' : ''
      }`}
    >
      <Sparkline data={sector.history.slice(-24)} up={up} />
      <div className="relative z-10 flex h-full min-h-[46px] flex-col justify-between">
        <div className="flex items-center justify-between gap-2">
          <span className="text-[9px] uppercase tracking-[0.16em] text-muted">{MARKET_LABEL[market]}</span>
          <span className={`tab-nums text-[9px] ${up ? 'text-up' : 'text-down'}`}>
            {up ? '▲' : '▼'}
          </span>
        </div>
        <div className="truncate text-[11px] font-medium leading-none text-fg-dim">{sector.name}</div>
        <div className="flex items-end justify-between gap-2">
          <span className={`tab-nums text-[15px] font-semibold leading-none ${up ? 'text-up' : 'text-down'}`}>
            {fmtValue(sector.indexValue)}
          </span>
          <span className={`tab-nums text-[10px] leading-none ${up ? 'text-up' : 'text-down'}`}>
            {up ? '+' : ''}
            {(sector.changePct * 100).toFixed(2)}%
          </span>
        </div>
      </div>
    </button>
  );
}

function IndexTrendChart({ sector }: { sector: MarketDepthSector }): JSX.Element {
  const option = useMemo<EChartsOption>(() => {
    const up = sector.changePct >= 0;
    return {
      grid: { left: 46, right: 18, top: 16, bottom: 28 },
      xAxis: {
        type: 'category',
        data: sector.history.map((_, i) => i),
        axisLabel: { color: '#6b7280', fontSize: 9 },
        axisTick: { show: false },
        axisLine: { lineStyle: { color: '#1c2230' } },
      },
      yAxis: {
        type: 'value',
        scale: true,
        axisLabel: { color: '#6b7280', fontSize: 9 },
        splitLine: { lineStyle: { color: '#1c2230', type: 'dashed' } },
      },
      tooltip: {
        trigger: 'axis',
        backgroundColor: '#0e1117',
        borderColor: '#2a3344',
        textStyle: { color: '#e6e9ef', fontSize: 11 },
        valueFormatter: (v) => fmtValue(Number(v)),
      },
      series: [
        {
          type: 'line',
          smooth: true,
          showSymbol: false,
          data: sector.history,
          lineStyle: { width: 2, color: up ? '#20cd8d' : '#f0556b' },
          areaStyle: { color: up ? 'rgba(32,205,141,0.09)' : 'rgba(240,85,107,0.09)' },
          animationDurationUpdate: 500,
        },
      ],
    };
  }, [sector]);
  const ref = useEChart(option);
  return <div ref={ref} className="h-full w-full" />;
}

export function MarketOverview({
  market,
  sourceMode,
  sectors,
  loading,
  delayed,
}: {
  market: Market;
  sourceMode: DataSourceMode;
  sectors: MarketDepthSector[];
  loading: boolean;
  delayed: boolean;
}): JSX.Element {
  const [popupSectorId, setPopupSectorId] = useState<string | null>(null);
  const popupSector = useMemo(
    () => sectors.find((s) => s.id === popupSectorId) ?? null,
    [popupSectorId, sectors],
  );
  const subtitle =
    sourceMode === 'auto' || sourceMode === 'mock' || sourceMode === 'yahoo'
      ? 'Sector indices · mock live'
      : delayed
        ? 'US indices · Yahoo delayed'
        : 'Sector indices · live source';

  return (
    <>
      <Card title="指数总览" subtitle={subtitle} corner="点击看走势">
        {sectors.length > 0 ? (
          <div className="scroll-thin grid h-full min-h-0 grid-flow-col auto-cols-[minmax(154px,1fr)] gap-2 overflow-x-auto">
            {sectors.map((sector) => (
              <IndexTile
                key={sector.id}
                sector={sector}
                market={market}
                onClick={() => setPopupSectorId(sector.id)}
              />
            ))}
          </div>
        ) : (
          <div className="flex h-full items-center justify-center text-xs text-muted">
            {loading ? '加载指数数据...' : `等待 ${sourceMode === 'futu' ? 'Futu' : '真实'} 板块指数数据接入`}
          </div>
        )}
      </Card>
      {popupSector && (
        <Popup
          title={`${popupSector.name} 实时走势`}
          subtitle={`${popupSector.changePct >= 0 ? '+' : ''}${(popupSector.changePct * 100).toFixed(2)}% · ${delayed ? 'Yahoo delayed' : sourceMode}`}
          onClose={() => setPopupSectorId(null)}
        >
          <IndexTrendChart sector={popupSector} />
        </Popup>
      )}
    </>
  );
}
