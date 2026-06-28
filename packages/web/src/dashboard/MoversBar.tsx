import { useMemo } from 'react';
import type { EChartsOption } from 'echarts';
import { Card } from './widgets/Card';
import { useTickers } from '../api/useTickers';
import { useEChart } from '../charts/useEChart';

export function MoversBar(): JSX.Element {
  const { data } = useTickers();

  const option = useMemo<EChartsOption>(() => {
    const sorted = (data ?? []).slice().sort((a, b) => a.changePct - b.changePct);
    const names = sorted.map((t) => t.symbol);
    const values = sorted.map((t) => Number((t.changePct * 100).toFixed(2)));
    return {
      grid: { left: 70, right: 40, top: 8, bottom: 8 },
      xAxis: { type: 'value', axisLabel: { color: '#6b7280', fontSize: 9 }, splitLine: { lineStyle: { color: '#1c2230' } } },
      yAxis: { type: 'category', data: names, axisLabel: { color: '#d1d4dc', fontSize: 10 }, axisLine: { lineStyle: { color: '#1c2230' } } },
      tooltip: { trigger: 'item', formatter: (p: any) => `${p.name}: ${p.value}%` },
      series: [
        {
          type: 'bar',
          data: values.map((v) => ({
            value: v,
            itemStyle: { color: v >= 0 ? '#16c784' : '#ea3943', borderRadius: 2 },
          })),
          label: { show: true, position: 'right', color: '#d1d4dc', fontSize: 9, formatter: '{c}%' },
          animationDurationUpdate: 500,
        },
      ],
    };
  }, [data]);

  const ref = useEChart(option);

  return (
    <Card title="涨跌排行" subtitle="Movers" corner="live">
      <div ref={ref} className="w-full h-full" />
    </Card>
  );
}
