/**
 * K 线蜡烛图组件（TradingView 开源图表库 lightweight-charts）
 * - 数据源：backend daily_prices（OHLC），本地渲染无外部 CDN 依赖
 * - 红涨绿跌（up #f0556b / down #20cd8d），深色主题与 tradeck 背景一致
 */
"use client";

import { useEffect, useRef } from "react";
import {
  CandlestickSeries,
  LineSeries,
  createChart,
  type IChartApi,
} from "lightweight-charts";

export interface KlinePoint {
  /** YYYY-MM-DD */
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
}

export interface MaOverlayPoint {
  /** YYYY-MM-DD */
  time: string;
  ma5: number | null;
  ma20: number | null;
  ma60: number | null;
}

/** MA 线配色（深色主题，参照 TradingView 惯例） */
const MA_LINES: {
  key: keyof Omit<MaOverlayPoint, "time">;
  label: string;
  color: string;
}[] = [
  { key: "ma5", label: "MA5", color: "#e8c15a" },
  { key: "ma20", label: "MA20", color: "#b07cc6" },
  { key: "ma60", label: "MA60", color: "#4ec9b0" },
];

export function TradingViewChart({
  data,
  maData,
  height = 420,
}: {
  data: KlinePoint[];
  maData?: MaOverlayPoint[];
  height?: number;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const chart = createChart(container, {
      autoSize: true,
      layout: {
        background: { color: "#090b11" },
        textColor: "#aab1bf",
        fontSize: 10,
      },
      grid: {
        vertLines: { color: "rgba(28, 34, 48, 0.5)" },
        horzLines: { color: "rgba(28, 34, 48, 0.5)" },
      },
      timeScale: {
        borderColor: "#1c2230",
        timeVisible: false,
      },
      rightPriceScale: {
        borderColor: "#1c2230",
      },
      crosshair: {
        vertLine: { color: "#2a3344", labelBackgroundColor: "#2a3344" },
        horzLine: { color: "#2a3344", labelBackgroundColor: "#2a3344" },
      },
    });
    chartRef.current = chart;

    // 红涨绿跌（A 股习惯）
    const series = chart.addSeries(CandlestickSeries, {
      upColor: "#f0556b",
      downColor: "#20cd8d",
      wickUpColor: "#f0556b",
      wickDownColor: "#20cd8d",
      borderVisible: false,
    });
    series.setData(data);

    // MA 均线 overlay（null 值跳过）
    if (maData && maData.length > 0) {
      for (const line of MA_LINES) {
        const lineSeries = chart.addSeries(LineSeries, {
          color: line.color,
          lineWidth: 1,
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerVisible: false,
        });
        lineSeries.setData(
          maData
            .filter((d) => d[line.key] != null)
            .map((d) => ({ time: d.time, value: d[line.key] as number }))
        );
      }
    }

    chart.timeScale().fitContent();

    return () => {
      chart.remove();
      chartRef.current = null;
    };
  }, [data, maData]);

  if (data.length === 0) {
    return (
      <div
        className="flex items-center justify-center text-xs text-muted-foreground"
        style={{ height }}
      >
        无 K 线数据
      </div>
    );
  }

  return (
    <div className="relative w-full overflow-hidden rounded-md" style={{ height }}>
      <div ref={containerRef} className="h-full w-full" />
      {maData && maData.length > 0 && (
        <div className="pointer-events-none absolute left-2 top-1 flex gap-2 text-[10px]">
          {MA_LINES.map((line) => (
            <span key={line.key} style={{ color: line.color }}>
              {line.label}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
