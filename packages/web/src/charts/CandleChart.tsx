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

interface Props {
  symbol: string;
  interval: OhlcvInterval;
}

export function CandleChart({ symbol, interval }: Props): JSX.Element {
  const containerRef = useRef<HTMLDivElement>(null);
  const seriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);

  const { data: history } = useOhlcv(symbol, interval);
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

  // (b) history: bulk setData.
  useEffect(() => {
    if (history && seriesRef.current) {
      seriesRef.current.setData(history.map(toLwcCandle));
    }
  }, [history]);

  // (c) realtime increment: update() overwrites last candle or appends a new one.
  useEffect(() => {
    if (liveCandle && seriesRef.current) {
      seriesRef.current.update(toLwcCandle(liveCandle));
    }
  }, [liveCandle]);

  return <div ref={containerRef} className="w-full h-full" />;
}
