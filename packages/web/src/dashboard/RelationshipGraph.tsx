import { useMemo } from 'react';
import type { EChartsOption } from 'echarts';
import type { Ticker } from '@tradeck/shared';
import { Card } from './widgets/Card';
import { useEChart } from '../charts/useEChart';
import { dedupeTickers, isIndex } from './tickerUtils';

/** 涨跌幅区间桶定义：[label, min, max, color] */
const BUCKETS = [
  { label: '< -3%', min: -Infinity, max: -0.03, color: '#f0556b' },
  { label: '-3% ~ -1%', min: -0.03, max: -0.01, color: '#e06a7a' },
  { label: '-1% ~ 0%', min: -0.01, max: 0, color: '#d08090' },
  { label: '0% ~ 1%', min: 0, max: 0.01, color: '#80c8a0' },
  { label: '1% ~ 3%', min: 0.01, max: 0.03, color: '#50d890' },
  { label: '> 3%', min: 0.03, max: Infinity, color: '#20cd8d' },
];

export function RelationshipGraph({ tickers }: { tickers: Ticker[] }): JSX.Element {
  const { buckets, stats } = useMemo(() => {
    const stocks = dedupeTickers(tickers).filter((t) => !isIndex(t));
    const counts = BUCKETS.map(() => 0);
    let upCount = 0;
    let downCount = 0;
    let flatCount = 0;
    let totalChange = 0;

    for (const t of stocks) {
      const pct = t.changePct;
      totalChange += pct;
      if (pct > 0.001) upCount++;
      else if (pct < -0.001) downCount++;
      else flatCount++;
      for (let i = 0; i < BUCKETS.length; i++) {
        if (pct >= BUCKETS[i].min && pct < BUCKETS[i].max) {
          counts[i]++;
          break;
        }
      }
    }

    return {
      buckets: BUCKETS.map((b, i) => ({ ...b, count: counts[i] })),
      stats: {
        total: stocks.length,
        up: upCount,
        down: downCount,
        flat: flatCount,
        avgChange: stocks.length > 0 ? totalChange / stocks.length : 0,
      },
    };
  }, [tickers]);

  const option = useMemo<EChartsOption>(() => {
    return {
      grid: { left: 70, right: 20, top: 30, bottom: 20 },
      xAxis: {
        type: 'category',
        data: buckets.map((b) => b.label),
        axisLabel: { color: '#6b7280', fontSize: 9 },
        axisLine: { lineStyle: { color: '#1c2230' } },
        axisTick: { show: false },
      },
      yAxis: {
        type: 'value',
        minInterval: 1,
        axisLabel: { color: '#6b7280', fontSize: 9 },
        splitLine: { lineStyle: { color: '#1c2230', type: 'dashed' } },
      },
      tooltip: {
        trigger: 'item',
        backgroundColor: '#0e1117',
        borderColor: '#2a3344',
        textStyle: { color: '#e6e9ef', fontSize: 11 },
        formatter: (p: any) => `<b>${p.name}</b><br/>${p.value} 只股票`,
      },
      series: [
        {
          type: 'bar',
          barWidth: '70%',
          data: buckets.map((b) => ({
            value: b.count,
            itemStyle: { color: b.color, borderRadius: [3, 3, 0, 0] },
          })),
          label: {
            show: true,
            position: 'top',
            color: '#aab1bf',
            fontSize: 10,
            formatter: '{c}',
          },
          animationDurationUpdate: 500,
        },
      ],
    };
  }, [buckets]);

  const ref = useEChart(option);
  const upPct = stats.total > 0 ? ((stats.up / stats.total) * 100).toFixed(0) : '0';

  return (
    <Card title="市场广度" subtitle="Market breadth · 涨跌分布">
      <div className="grid grid-cols-1 gap-2">
        <div className="flex items-center justify-between text-xs">
          <span className="text-up">
            涨 {stats.up} 家 ({upPct}%)
          </span>
          <span className="text-muted">平 {stats.flat} 家</span>
          <span className="text-down">
            跌 {stats.down} 家
          </span>
        </div>
        <div className="flex items-center justify-between text-[10px] text-muted">
          <span>共 {stats.total} 只</span>
          <span>
            平均涨幅:{' '}
            <span className={stats.avgChange >= 0 ? 'text-up' : 'text-down'}>
              {stats.avgChange >= 0 ? '+' : ''}
              {(stats.avgChange * 100).toFixed(2)}%
            </span>
          </span>
        </div>
        <div ref={ref} className="h-[160px] w-full" />
      </div>
    </Card>
  );
}
