import { useMemo } from 'react';
import type { EChartsOption } from 'echarts';
import type { Ticker } from '@tradeck/shared';
import { Card } from './widgets/Card';
import { useEChart } from '../charts/useEChart';
import { dedupeTickers, isIndex } from './tickerUtils';
import { MARKET_LABEL, type Market } from './market';

/** changePct → 颜色（涨绿跌红，幅度越大越亮） */
function changePctToColor(changePct: number): string {
  const pct = changePct * 100;
  const mag = Math.min(1, Math.abs(pct) / 5); // ±5% 满色
  if (pct >= 0) {
    const alpha = 0.25 + mag * 0.55;
    return `rgba(32, 205, 141, ${alpha.toFixed(2)})`;
  }
  const alpha = 0.25 + mag * 0.55;
  return `rgba(240, 85, 107, ${alpha.toFixed(2)})`;
}

export function Heatmap({ tickers }: { tickers: Ticker[] }): JSX.Element {
  const option = useMemo<EChartsOption>(() => {
    const stocks = dedupeTickers(tickers).filter((t) => !isIndex(t));
    // 按 market 分组
    const groups: Record<string, Ticker[]> = { cn: [], hk: [], us: [] };
    for (const t of stocks) {
      const m = (t.market ?? 'us') as keyof typeof groups;
      if (groups[m]) groups[m].push(t);
    }

    const data = Object.entries(groups)
      .filter(([, list]) => list.length > 0)
      .map(([marketKey, list]) => ({
        name: MARKET_LABEL[marketKey as Market] ?? marketKey,
        itemStyle: { borderColor: '#1c2230', borderWidth: 2 },
        children: list.map((t) => ({
          name: t.name ?? t.symbol,
          value: t.volume ?? 1,
          changePct: t.changePct,
          symbol: t.symbol,
          price: t.price,
          itemStyle: { color: changePctToColor(t.changePct) },
        })),
      }));

    return {
      tooltip: {
        backgroundColor: '#0e1117',
        borderColor: '#2a3344',
        textStyle: { color: '#e6e9ef', fontSize: 11 },
        formatter: (info: any) => {
          const d = info.data;
          if (d.children) return `<b>${d.name}</b> (${d.children.length} 只)`;
          const pct = (d.changePct * 100).toFixed(2);
          const color = d.changePct >= 0 ? '#20cd8d' : '#f0556b';
          return `<b>${d.name}</b><br/>${d.symbol}<br/>价格: ${d.price.toFixed(2)}<br/><span style="color:${color}">${d.changePct >= 0 ? '+' : ''}${pct}%</span>`;
        },
      },
      series: [
        {
          type: 'treemap',
          data,
          roam: false,
          nodeClick: false,
          breadcrumb: { show: false },
          label: {
            show: true,
            color: '#e6e9ef',
            fontSize: 10,
            formatter: (p: any) => {
              const d = p.data;
              if (d.children) return d.name;
              const pct = (d.changePct * 100).toFixed(1);
              return `{n|${d.name}}\n{p|${d.changePct >= 0 ? '+' : ''}${pct}%}`;
            },
            rich: {
              n: { fontSize: 10, color: '#e6e9ef', lineHeight: 14 },
              p: { fontSize: 9, color: '#aab1bf', lineHeight: 12 },
            },
          },
          upperLabel: { show: true, height: 18, color: '#6b7280', fontSize: 9 },
          itemStyle: { borderColor: '#0e1117', borderWidth: 1, gapWidth: 2 },
          levels: [
            { itemStyle: { borderColor: '#1c2230', borderWidth: 2 } },
            { color: ['#0e1117'], itemStyle: { borderColor: '#1c2230', borderWidth: 1 } },
          ],
        },
      ],
    };
  }, [tickers]);

  const ref = useEChart(option);

  return (
    <Card title="个股热力图" subtitle="Treemap · 颜色=涨跌 大小=成交量">
      <div ref={ref} className="h-full w-full" />
    </Card>
  );
}
