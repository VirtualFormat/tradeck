import { useEffect, useRef } from 'react';
import * as echarts from 'echarts';

/**
 * Mounts an ECharts instance into a div and applies `option` on every change.
 * notMerge:false preserves animations between live updates. StrictMode-safe:
 * disposes on unmount and resizes via ResizeObserver.
 */
export function useEChart(option: echarts.EChartsOption): React.RefObject<HTMLDivElement> {
  const ref = useRef<HTMLDivElement>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);

  useEffect(() => {
    if (!ref.current) return;
    const chart = echarts.init(ref.current, undefined, { renderer: 'canvas' });
    chartRef.current = chart;
    const ro = new ResizeObserver(() => chart.resize());
    ro.observe(ref.current);
    return () => {
      ro.disconnect();
      chart.dispose();
      chartRef.current = null;
    };
  }, []);

  useEffect(() => {
    chartRef.current?.setOption(option, { notMerge: false });
  }, [option]);

  return ref;
}
