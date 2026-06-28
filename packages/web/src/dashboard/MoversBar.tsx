import { useMemo } from 'react';
import type { EChartsOption } from 'echarts';
import { Card } from './widgets/Card';
import { BarsSkeleton } from './widgets/Skeleton';
import { useTickers } from '../api/useTickers';
import { useEChart } from '../charts/useEChart';

export function MoversBar(): JSX.Element {
  const { data, isLoading } = useTickers();

  const option = useMemo<EChartsOption>(() => {
    const sorted = (data ?? []).slice().sort((a, b) => a.changePct - b.changePct);
    const names = sorted.map((t) => t.symbol);
    const values = sorted.map((t) => Number((t.changePct * 100).toFixed(2)));
    return {
      grid: { left: 72, right: 48, top: 8, bottom: 8 },
      xAxis: {
        type: 'value',
        axisLabel: { color: '#6b7280', fontSize: 9, formatter: '{value}%' },
        splitLine: { lineStyle: { color: '#1c2230', type: 'dashed' } },
      },
      yAxis: {
        type: 'category',
        data: names,
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
          const col = p.value >= 0 ? '#20cd8d' : '#f0556b';
          return `<b>${p.name}</b>&nbsp;<span style="color:${col}">${p.value >= 0 ? '+' : ''}${p.value}%</span>`;
        },
      },
      series: [
        {
          type: 'bar',
          barWidth: '55%',
          data: values.map((v) => ({
            value: v,
            itemStyle: {
              color: v >= 0 ? '#20cd8d' : '#f0556b',
              borderRadius: v >= 0 ? [0, 3, 3, 0] : [3, 0, 0, 3],
            },
          })),
          label: {
            show: true,
            position: 'right',
            color: '#aab1bf',
            fontSize: 9,
            formatter: (p: any) => `${p.value >= 0 ? '+' : ''}${p.value}%`,
          },
          animationDurationUpdate: 500,
        },
      ],
    };
  }, [data]);

  const ref = useEChart(option);

  return (
    <Card title="涨跌排行" subtitle="Movers" corner="live">
      <div className="relative h-full w-full">
        <div ref={ref} className="h-full w-full" />
        {isLoading && (
          <div className="absolute inset-0">
            <BarsSkeleton />
          </div>
        )}
      </div>
    </Card>
  );
}
