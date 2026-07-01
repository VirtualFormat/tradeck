import { useMemo, useState } from 'react';
import type { EChartsOption } from 'echarts';
import type { Ticker } from '@tradeck/shared';
import { Card } from './widgets/Card';
import { useEChart } from '../charts/useEChart';
import { useMockMarketDepth } from './mock/marketDepth';
import type { DataSourceMode, Market } from './market';

type Mode = 'up' | 'down';

export function MoversBar({
  market,
  sourceMode,
  tickers,
}: {
  market: Market;
  sourceMode: DataSourceMode;
  tickers: Ticker[];
}): JSX.Element {
  const sectors = useMockMarketDepth(market);
  const [mode, setMode] = useState<Mode>('up');

  const rows = useMemo(() => {
    // auto/eastmoney/yahoo 模式：有 tickers 就用 tickers，无则 fallback mock sectors
    if (tickers.length > 0) {
      return tickers
        .map((t) => ({
          symbol: t.symbol,
          name: t.name ?? t.symbol,
          sectorName: t.source,
          changePct: t.changePct,
        }))
        .sort((a, b) => (mode === 'up' ? b.changePct - a.changePct : a.changePct - b.changePct))
        .slice(0, 14);
    }
    const stocks = sectors.flatMap((s) => s.stocks.map((stock) => ({ ...stock, sectorName: s.name })));
    return stocks
      .sort((a, b) => (mode === 'up' ? b.changePct - a.changePct : a.changePct - b.changePct))
      .slice(0, 14);
  }, [mode, sectors, sourceMode, tickers]);

  const option = useMemo<EChartsOption>(() => {
    const chartRows = rows;
    const isUp = mode === 'up';
    return {
      grid: { left: 86, right: 54, top: 6, bottom: 8 },
      xAxis: {
        type: 'value',
        axisLabel: { color: '#6b7280', fontSize: 9, formatter: '{value}%' },
        splitLine: { lineStyle: { color: '#1c2230', type: 'dashed' } },
      },
      yAxis: {
        type: 'category',
        inverse: true,
        data: chartRows.map((s) => s.name),
        axisLabel: { color: '#aab1bf', fontSize: 10 },
        axisLine: { show: false },
        axisTick: { show: false },
      },
      tooltip: {
        trigger: 'item',
        backgroundColor: '#0e1117',
        borderColor: '#2a3344',
        textStyle: { color: '#e6e9ef', fontSize: 11 },
        formatter: (p: any) => {
          const row = chartRows[p.dataIndex];
          const value = Number(p.value);
          const color = value >= 0 ? '#20cd8d' : '#f0556b';
          return `<b>${row.name}</b><br/>${row.symbol} · ${row.sectorName}<br/><span style="color:${color}">${value >= 0 ? '+' : ''}${value.toFixed(2)}%</span>`;
        },
      },
      series: [
        {
          type: 'bar',
          realtimeSort: true,
          barWidth: 8,
          data: chartRows.map((s) => {
            const value = Number((s.changePct * 100).toFixed(2));
            return {
              value,
              itemStyle: {
                color: value >= 0 ? '#20cd8d' : '#f0556b',
                borderRadius: value >= 0 ? [0, 3, 3, 0] : [3, 0, 0, 3],
              },
            };
          }),
          label: {
            show: true,
            position: isUp ? 'right' : 'left',
            color: '#aab1bf',
            fontSize: 9,
            formatter: (p: any) => `${p.value >= 0 ? '+' : ''}${Number(p.value).toFixed(2)}%`,
          },
          animationDurationUpdate: 650,
          animationEasingUpdate: 'cubicInOut',
        },
      ],
    };
  }, [mode, rows]);

  useEChart(option);

  const maxAbs = Math.max(0.01, ...rows.map((row) => Math.abs(row.changePct * 100)));

  const tabs = (
    <div className="inline-flex rounded-md border border-border bg-panel-2 p-0.5">
      {[
        ['up', '涨幅TOP'],
        ['down', '跌幅TOP'],
      ].map(([key, label]) => (
        <button
          key={key}
          type="button"
          onClick={() => setMode(key as Mode)}
          className={`rounded px-2 py-0.5 text-[10px] transition-colors ${
            mode === key ? 'bg-accent/15 text-fg' : 'text-muted hover:text-fg'
          }`}
        >
          {label}
        </button>
      ))}
    </div>
  );

  return (
    <Card title="热门股票榜" subtitle="Dynamic ranking" corner={tabs}>
      <div className="scroll-thin h-full overflow-y-auto pt-1">
        <div className="space-y-1.5">
          {rows.map((row, index) => {
            const pct = row.changePct * 100;
            const up = pct >= 0;
            const width = `${Math.max(4, (Math.abs(pct) / maxAbs) * 100)}%`;
            const ticker = tickers.find((t) => t.symbol === row.symbol);
            return (
              <div key={row.symbol} className="grid grid-cols-[22px_1fr_64px] items-center gap-2 text-[11px]">
                <span className="tab-nums text-muted">{String(index + 1).padStart(2, '0')}</span>
                <div className="min-w-0">
                  <div className="flex items-center justify-between gap-2">
                    <span className="truncate text-fg">{row.name}</span>
                    <span className="tab-nums shrink-0 text-muted">{ticker?.price.toFixed(2) ?? '--'}</span>
                  </div>
                  <div className="mt-1 h-1.5 overflow-hidden rounded bg-panel-2">
                    <div
                      className={`h-full rounded ${up ? 'bg-up' : 'bg-down'}`}
                      style={{ width }}
                    />
                  </div>
                  <div className="mt-0.5 truncate text-[9px] text-muted">{row.symbol} · {row.sectorName}</div>
                </div>
                <span className={`tab-nums text-right ${up ? 'text-up' : 'text-down'}`}>
                  {up ? '+' : ''}{pct.toFixed(2)}%
                </span>
              </div>
            );
          })}
        </div>
      </div>
    </Card>
  );
}
