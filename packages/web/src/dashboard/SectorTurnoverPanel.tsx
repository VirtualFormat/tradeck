import { useMemo } from 'react';
import type { EChartsOption } from 'echarts';
import type { Ticker } from '@tradeck/shared';
import { Card } from './widgets/Card';
import { useEChart } from '../charts/useEChart';
import { dedupeTickers, isIndex } from './tickerUtils';

/** 格式化成交量：万手 / 亿手 */
function fmtVolume(value: number): string {
  if (value >= 100_000_000) return `${(value / 100_000_000).toFixed(1)}亿`;
  if (value >= 10_000) return `${(value / 10_000).toFixed(0)}万`;
  return value.toFixed(0);
}

export function SectorTurnoverPanel({ tickers }: { tickers: Ticker[] }): JSX.Element {
  const rows = useMemo(() => {
    return dedupeTickers(tickers)
      .filter((t) => !isIndex(t) && t.volume != null && t.volume > 0)
      .sort((a, b) => (b.volume ?? 0) - (a.volume ?? 0))
      .slice(0, 12);
  }, [tickers]);

  const option = useMemo<EChartsOption>(() => {
    const chartRows = rows;
    return {
      grid: { left: 78, right: 58, top: 8, bottom: 10 },
      xAxis: {
        type: 'value',
        axisLabel: { color: '#6b7280', fontSize: 9, formatter: (v: number) => fmtVolume(v) },
        splitLine: { lineStyle: { color: '#1c2230', type: 'dashed' } },
      },
      yAxis: {
        type: 'category',
        inverse: true,
        data: chartRows.map((s) => s.name ?? s.symbol),
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
          const color = row.changePct >= 0 ? '#20cd8d' : '#f0556b';
          const pct = (row.changePct * 100).toFixed(2);
          return `<b>${row.name ?? row.symbol}</b><br/>${row.symbol}<br/>价格: ${row.price.toFixed(2)}<br/>成交量: ${fmtVolume(row.volume ?? 0)}<br/><span style="color:${color}">${row.changePct >= 0 ? '+' : ''}${pct}%</span>`;
        },
      },
      series: [
        {
          type: 'bar',
          realtimeSort: true,
          barWidth: 10,
          data: chartRows.map((s) => ({
            value: Number((s.volume ?? 0).toFixed(0)),
            itemStyle: {
              borderRadius: [0, 3, 3, 0],
              color: {
                type: 'linear',
                x: 0,
                y: 0,
                x2: 1,
                y2: 0,
                colorStops: [
                  { offset: 0, color: s.changePct >= 0 ? 'rgba(32,205,141,0.18)' : 'rgba(240,85,107,0.18)' },
                  { offset: 1, color: s.changePct >= 0 ? 'rgba(32,205,141,0.92)' : 'rgba(240,85,107,0.92)' },
                ],
              },
            },
          })),
          label: {
            show: true,
            position: 'right',
            color: '#aab1bf',
            fontSize: 9,
            formatter: (p: any) => fmtVolume(Number(p.value)),
          },
          animationDurationUpdate: 700,
          animationEasingUpdate: 'cubicInOut',
        },
      ],
    };
  }, [rows]);

  const ref = useEChart(option);

  return (
    <Card title="个股成交量排行" subtitle="Volume ranking · 动态排序">
      {rows.length > 0 ? (
        <div ref={ref} className="h-full w-full" />
      ) : (
        <div className="flex h-full items-center justify-center text-xs text-muted">
          等待成交量数据...
        </div>
      )}
    </Card>
  );
}
