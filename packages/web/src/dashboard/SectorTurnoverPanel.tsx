import { useCallback, useMemo } from 'react';
import type { EChartsOption } from 'echarts';
import type { MarketDepthSector } from '@tradeck/shared';
import { Card } from './widgets/Card';
import { useEChart } from '../charts/useEChart';
import type { DataSourceMode, Market } from './market';

function fmtTurnover(value: number): string {
  return `${(value / 100_000_000).toFixed(0)}亿`;
}

interface Props {
  market: Market;
  sourceMode: DataSourceMode;
  sectors: MarketDepthSector[];
  loading: boolean;
  selectedSectorId: string | null;
  onSectorSelect: (sectorId: string) => void;
}

export function SectorTurnoverPanel({
  sourceMode,
  sectors,
  loading,
  selectedSectorId,
  onSectorSelect,
}: Props): JSX.Element {
  const rows = useMemo(
    () => sectors.slice().sort((a, b) => b.turnover - a.turnover).slice(0, 12),
    [sectors],
  );

  const option = useMemo<EChartsOption>(() => {
    const chartRows = rows;
    return {
      grid: { left: 78, right: 58, top: 8, bottom: 10 },
      xAxis: {
        type: 'value',
        axisLabel: { color: '#6b7280', fontSize: 9, formatter: (v: number) => fmtTurnover(v) },
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
          const color = row.changePct >= 0 ? '#20cd8d' : '#f0556b';
          return `<b>${row.name}</b><br/>成交额 ${fmtTurnover(row.turnover)}<br/><span style="color:${color}">${row.changePct >= 0 ? '+' : ''}${(row.changePct * 100).toFixed(2)}%</span><br/>点击查看成分股`;
        },
      },
      series: [
        {
          type: 'bar',
          realtimeSort: true,
          barWidth: 10,
          data: chartRows.map((s) => ({
            id: s.id,
            value: Number(s.turnover.toFixed(0)),
            itemStyle: {
              borderRadius: [0, 3, 3, 0],
              color:
                selectedSectorId === s.id
                  ? '#4d8dff'
                  : {
                      type: 'linear',
                      x: 0,
                      y: 0,
                      x2: 1,
                      y2: 0,
                      colorStops: [
                        { offset: 0, color: 'rgba(77,141,255,0.18)' },
                        { offset: 1, color: 'rgba(77,141,255,0.92)' },
                      ],
                    },
            },
          })),
          label: {
            show: true,
            position: 'right',
            color: '#aab1bf',
            fontSize: 9,
            formatter: (p: any) => fmtTurnover(Number(p.value)),
          },
          animationDurationUpdate: 700,
          animationEasingUpdate: 'cubicInOut',
        },
      ],
    };
  }, [rows, selectedSectorId]);

  const handleClick = useCallback(
    (params: unknown) => {
      const data = (params as { data?: { id?: string } }).data;
      if (data?.id) onSectorSelect(data.id);
    },
    [onSectorSelect],
  );

  const ref = useEChart(option, { click: handleClick });

  return (
    <Card title="板块交易额排行" subtitle="Turnover ranking" corner="动态排序">
      {rows.length > 0 ? (
        <div ref={ref} className="h-full w-full" />
      ) : (
        <div className="flex h-full items-center justify-center text-xs text-muted">
          {loading ? '加载板块成交额数据...' : `等待 ${sourceMode === 'futu' ? 'Futu' : '真实'} 板块成交额数据接入`}
        </div>
      )}
    </Card>
  );
}
