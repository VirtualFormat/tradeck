import { useMemo } from 'react';
import type { EChartsOption } from 'echarts';
import { Card } from './widgets/Card';
import { TilesSkeleton } from './widgets/Skeleton';
import { useTickers } from '../api/useTickers';
import { useEChart } from '../charts/useEChart';
import { filterByMarket, type Market } from './market';

/** Blend a dim panel tone toward the theme up/down color by change magnitude. */
function heatColor(changePct: number): string {
  const mag = Math.min(1, Math.abs(changePct) / 0.02); // saturate at ±2%
  const base = [0x16, 0x1c, 0x26]; // panel-ish neutral
  const target = changePct >= 0 ? [0x20, 0xcd, 0x8d] : [0xf0, 0x55, 0x6b];
  const mix = base.map((b, i) => Math.round(b + (target[i] - b) * (0.25 + mag * 0.6)));
  return `rgb(${mix[0]}, ${mix[1]}, ${mix[2]})`;
}

export function Heatmap({ market }: { market: Market }): JSX.Element {
  const { data, isLoading } = useTickers();

  const option = useMemo<EChartsOption>(() => {
    const nodes = filterByMarket(data, market).map((t) => ({
      name: t.name ?? t.symbol,
      value: Math.max(1, t.volume ?? 1),
      changePct: t.changePct,
      itemStyle: { color: heatColor(t.changePct) },
    }));
    return {
      tooltip: {
        backgroundColor: '#0e1117',
        borderColor: '#2a3344',
        textStyle: { color: '#e6e9ef', fontSize: 11 },
        formatter: (p: any) => {
          const c = p.data.changePct as number;
          const col = c >= 0 ? '#20cd8d' : '#f0556b';
          return `<b>${p.name}</b><br/>vol ${Number(p.value).toLocaleString('en-US', { maximumFractionDigits: 2 })}<br/><span style="color:${col}">${c >= 0 ? '+' : ''}${(c * 100).toFixed(2)}%</span>`;
        },
      },
      series: [
        {
          type: 'treemap',
          roam: false,
          nodeClick: false,
          breadcrumb: { show: false },
          label: {
            show: true,
            color: '#fff',
            fontSize: 11,
            fontWeight: 500,
            textShadowColor: 'rgba(0,0,0,0.5)',
            textShadowBlur: 3,
          },
          itemStyle: { borderColor: '#090b11', borderWidth: 3, gapWidth: 3, borderRadius: 4 },
          data: nodes,
          animationDurationUpdate: 500,
        },
      ],
    };
  }, [data, market]);

  const ref = useEChart(option);

  return (
    <Card title="热力图" subtitle="Heatmap · vol × change" corner="live">
      <div className="relative h-full w-full">
        <div ref={ref} className="h-full w-full" />
        {isLoading && (
          <div className="absolute inset-0">
            <TilesSkeleton />
          </div>
        )}
      </div>
    </Card>
  );
}
