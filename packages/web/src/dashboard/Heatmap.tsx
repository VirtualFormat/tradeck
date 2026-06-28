import { useMemo } from 'react';
import type { EChartsOption } from 'echarts';
import { Card } from './widgets/Card';
import { useTickers } from '../api/useTickers';
import { useEChart } from '../charts/useEChart';

/** Blend toward green (up) / red (down) by change magnitude. */
function heatColor(changePct: number): string {
  const mag = Math.min(1, Math.abs(changePct) / 0.02); // saturate at ±2%
  if (changePct >= 0) {
    const g = Math.round(0x40 + mag * 0x80);
    return `rgb(20, ${g}, 80)`;
  }
  const r = Math.round(0x40 + mag * 0xa0);
  return `rgb(${r}, 40, 60)`;
}

export function Heatmap(): JSX.Element {
  const { data } = useTickers();

  const option = useMemo<EChartsOption>(() => {
    const nodes = (data ?? []).map((t) => ({
      name: t.symbol,
      value: Math.max(1, t.volume ?? 1),
      changePct: t.changePct,
      itemStyle: { color: heatColor(t.changePct) },
    }));
    return {
      tooltip: {
        formatter: (p: any) =>
          `${p.name}<br/>vol ${Number(p.value).toFixed(2)}<br/>${(p.data.changePct * 100).toFixed(2)}%`,
      },
      series: [
        {
          type: 'treemap',
          roam: false,
          nodeClick: false,
          breadcrumb: { show: false },
          label: { show: true, color: '#fff', fontSize: 11 },
          itemStyle: { borderColor: '#0b0e14', borderWidth: 2, gapWidth: 2 },
          data: nodes,
          animationDurationUpdate: 500,
        },
      ],
    };
  }, [data]);

  const ref = useEChart(option);

  return (
    <Card title="热力图" subtitle="Heatmap · vol × change" corner="live">
      <div ref={ref} className="w-full h-full" />
    </Card>
  );
}
