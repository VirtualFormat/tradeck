import { useMemo } from 'react';
import type { EChartsOption } from 'echarts';
import type { MarketDepthSector } from '@tradeck/shared';
import { Popup } from './widgets/Popup';
import { useEChart } from '../charts/useEChart';

function fmtTurnover(value: number): string {
  return `${(value / 100_000_000).toFixed(1)}亿`;
}

export function SectorStockPopup({
  sector,
  onClose,
}: {
  sector: MarketDepthSector;
  onClose: () => void;
}): JSX.Element {
  const rows = useMemo(
    () => sector.stocks.slice().sort((a, b) => b.changePct - a.changePct),
    [sector],
  );

  const option = useMemo<EChartsOption>(() => {
    return {
      grid: { left: 90, right: 62, top: 12, bottom: 20 },
      xAxis: {
        type: 'value',
        axisLabel: { color: '#6b7280', fontSize: 9, formatter: '{value}%' },
        splitLine: { lineStyle: { color: '#1c2230', type: 'dashed' } },
      },
      yAxis: {
        type: 'category',
        inverse: true,
        data: rows.map((s) => s.name),
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
          const row = rows[p.dataIndex];
          const value = Number(p.value);
          const color = value >= 0 ? '#20cd8d' : '#f0556b';
          return `<b>${row.name}</b><br/>${row.symbol} · 成交额 ${fmtTurnover(row.turnover)}<br/><span style="color:${color}">${value >= 0 ? '+' : ''}${value.toFixed(2)}%</span>`;
        },
      },
      series: [
        {
          type: 'bar',
          barWidth: 12,
          data: rows.map((s) => {
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
            position: 'right',
            color: '#aab1bf',
            fontSize: 9,
            formatter: (p: any) => `${Number(p.value) >= 0 ? '+' : ''}${Number(p.value).toFixed(2)}%`,
          },
          animationDurationUpdate: 600,
          animationEasingUpdate: 'cubicInOut',
        },
      ],
    };
  }, [rows]);

  const ref = useEChart(option);

  return (
    <Popup
      title={`${sector.name} 成分股涨幅排行`}
      subtitle={`成交额 ${fmtTurnover(sector.turnover)} · 热度 ${sector.heat.toFixed(0)} · 涨幅倒序`}
      onClose={onClose}
    >
      <div ref={ref} className="h-full w-full" />
    </Popup>
  );
}
