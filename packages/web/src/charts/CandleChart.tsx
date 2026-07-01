import { useEffect, useRef } from 'react';
import {
  CandlestickSeries,
  createChart,
  type CandlestickData,
  type IChartApi,
  type ISeriesApi,
  type Time,
} from 'lightweight-charts';
import type { OHLCV, OhlcvInterval } from '@tradeck/shared';
import { useOhlcv } from '../api/useOhlcv';
import { useMarketStore } from '../stores/marketStore';
import { ChartSkeleton } from '../dashboard/widgets/Skeleton';

/** OHLCV (epoch ms) -> lightweight-charts candle (UNIX seconds). */
function toLwcCandle(c: OHLCV): CandlestickData {
  return {
    time: (Math.floor(c.ts / 1000)) as Time,
    open: c.o,
    high: c.h,
    low: c.l,
    close: c.c,
  };
}

/**
 * 去重 + 升序排序。lightweight-charts 的 setData 要求时间戳严格升序且无重复，
 * 否则抛异常导致组件崩溃（切换数据源时 Yahoo 返回的数据可能乱序或含重复）。
 */
function dedupeAndSort(data: CandlestickData[]): CandlestickData[] {
  const map = new Map<number, CandlestickData>();
  for (const d of data) {
    const key = d.time as number;
    map.set(key, d); // 重复时后者覆盖
  }
  return [...map.values()].sort((a, b) => (a.time as number) - (b.time as number));
}

interface Props {
  symbol: string;
  interval: OhlcvInterval;
}

export function CandleChart({ symbol, interval }: Props): JSX.Element {
  const containerRef = useRef<HTMLDivElement>(null);
  const seriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);

  const { data: history, isLoading } = useOhlcv(symbol, interval);
  const liveCandle = useMarketStore((s) => s.liveCandleBySymbol[symbol]);

  // (a) create chart once; StrictMode-safe via full cleanup.
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const chart: IChartApi = createChart(container, {
      width: container.clientWidth,
      height: container.clientHeight,
      autoSize: false,
      layout: { background: { color: '#0e1117' }, textColor: '#d1d4dc' },
      grid: { vertLines: { color: '#1c2230' }, horzLines: { color: '#1c2230' } },
      timeScale: { timeVisible: true, secondsVisible: false },
    });
    seriesRef.current = chart.addSeries(CandlestickSeries);

    // follow both width and height of the grid item
    const ro = new ResizeObserver(() =>
      chart.applyOptions({ width: container.clientWidth, height: container.clientHeight }),
    );
    ro.observe(container);

    return () => {
      ro.disconnect();
      chart.remove();
      seriesRef.current = null;
    };
  }, []);

  // (b) history: bulk setData. 去重 + 排序，try/catch 防止异常导致白屏。
  useEffect(() => {
    if (history && seriesRef.current) {
      try {
        const clean = dedupeAndSort(history.map(toLwcCandle));
        seriesRef.current.setData(clean);
      } catch (err) {
        console.error('setData failed for', symbol, err);
      }
    }
  }, [history, symbol]);

  // (c) realtime increment: update() overwrites last candle or appends a new one.
  useEffect(() => {
    if (liveCandle && seriesRef.current) {
      try {
        seriesRef.current.update(toLwcCandle(liveCandle));
      } catch (err) {
        // update 失败通常是因为时间戳比已有数据更早，忽略即可
        console.warn('update failed for', symbol, err);
      }
    }
  }, [liveCandle, symbol]);

  return (
    <div className="relative h-full w-full">
      <div ref={containerRef} className="h-full w-full" />
      {isLoading && (
        <div className="absolute inset-0 bg-panel">
          <ChartSkeleton />
        </div>
      )}
    </div>
  );
}
