/**
 * K 线回放弹窗（阶段 N3）：shadcn Dialog 包裹 lightweight-charts K 线
 * - 单笔回放：买卖点箭头 markers + 买/卖价两条价格线
 * - 标的回放（选股分析行）：多笔 trades 传入，同日同方向合并 marker，
 *   全画幅买卖价虚线价格线（首末笔区间交叠时省略价线）
 * - 数据经 /api/historical 代理（该路由仅支持 days 参数，实际拉取窗口为
 *   「今天向前推 最早入场前45天~最晚出场后20天 的天数」，回测区间早于
 *   当前日期时图上会多带尾部数据，不影响买卖点标注），失败 EmptyState 降级
 * 豁免登记：lightweight-charts 为 K 线专用库（同 tradingview-chart.tsx 的既有豁免），
 * 不经 ui/chart 的 recharts 原语。
 */
"use client";

import { useEffect, useState } from "react";
import {
  CandlestickSeries,
  createChart,
  createSeriesMarkers,
  LineStyle,
  type IChartApi,
  type ISeriesApi,
  type SeriesMarker,
  type Time,
} from "lightweight-charts";

import { EmptyState } from "@/components/empty-state";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";

import {
  exitReasonLabel,
  fmtMoney,
  fmtNum,
  fmtPct,
  pnlStyle,
  type BacktestTrade,
} from "./types";

/** 图表数据窗口的日期余量（自然日，参照 TradeKlineModal 口径） */
const LEAD_DAYS = 45;
const TAIL_DAYS = 20;

/** 单笔回放：持仓期内用点状虚线价格线模拟区间着色（近似连续填充） */
const HOLDING_LINE_STYLE = LineStyle.SparseDotted;
/** 标的回放（多笔交易）：全画幅虚线价格线，避免区间点线连成一片 */
const SYMBOL_LINE_STYLE = LineStyle.Dashed;

interface HistoricalRow {
  date: string;
  open: number | null;
  high: number | null;
  low: number | null;
  close: number | null;
}

interface KlinePoint {
  /** YYYY-MM-DD */
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
}

interface PriceLine {
  price: number;
  title: string;
  color: string;
}

function addDays(date: string, days: number): string {
  const d = new Date(`${date}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

function shortDate(date: string | null | undefined): string {
  return date ? date.slice(0, 10) : "";
}

/**
 * 买卖 markers：同日同方向多笔合并为一个箭头（多箭头会重叠），
 * 价格异则标签显示区间；同日买+卖允许共存（上下两个位置）
 */
function buildMarkers(trades: BacktestTrade[]): SeriesMarker<Time>[] {
  type Agg = { count: number; lo: number; hi: number };
  const byDate = new Map<string, { buy?: Agg; sell?: Agg }>();
  const add = (date: string, side: "buy" | "sell", price: number) => {
    let g = byDate.get(date);
    if (!g) {
      g = {};
      byDate.set(date, g);
    }
    const s = g[side];
    if (s) {
      s.count += 1;
      s.lo = Math.min(s.lo, price);
      s.hi = Math.max(s.hi, price);
    } else {
      g[side] = { count: 1, lo: price, hi: price };
    }
  };
  const label = (s: Agg): string => {
    const range =
      s.lo === s.hi ? fmtNum(s.lo) : `${fmtNum(s.lo)}~${fmtNum(s.hi)}`;
    return s.count > 1 ? `${range} ×${s.count}` : range;
  };
  for (const t of trades) {
    const entry = shortDate(t.entry_date);
    const exit = shortDate(t.exit_date);
    if (entry && t.entry_price != null) add(entry, "buy", t.entry_price);
    if (exit && t.exit_price != null) add(exit, "sell", t.exit_price);
  }
  const markers: SeriesMarker<Time>[] = [];
  for (const [date, g] of byDate) {
    if (g.buy) {
      markers.push({
        time: date,
        position: "belowBar",
        shape: "arrowUp",
        color: "var(--up)",
        text: `买 ${label(g.buy)}`,
      });
    }
    if (g.sell) {
      markers.push({
        time: date,
        position: "aboveBar",
        shape: "arrowDown",
        color: "var(--down)",
        text: `卖 ${label(g.sell)}`,
      });
    }
  }
  return markers.sort((a, b) => String(a.time).localeCompare(String(b.time)));
}

/** K 线渲染主体：图表与 Dialog 布局解耦（close 淡出动画期间图表保持挂载） */
function ReplayChart({
  data,
  markers,
  priceLines,
  lineStyle,
}: {
  data: KlinePoint[];
  markers: SeriesMarker<Time>[];
  priceLines: PriceLine[];
  lineStyle: LineStyle;
}) {
  const [container, setContainer] = useState<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!container || data.length === 0) return;

    const chart: IChartApi = createChart(container, {
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

    // 红涨绿跌（A 股习惯，与 tradingview-chart.tsx 一致）
    const series: ISeriesApi<"Candlestick"> = chart.addSeries(
      CandlestickSeries,
      {
        upColor: "#f0556b",
        downColor: "#20cd8d",
        wickUpColor: "#f0556b",
        wickDownColor: "#20cd8d",
        borderVisible: false,
      }
    );
    series.setData(data);

    for (const line of priceLines) {
      series.createPriceLine({
        price: line.price,
        title: line.title,
        color: line.color,
        lineWidth: 1,
        lineStyle,
      });
    }

    if (markers.length > 0) {
      createSeriesMarkers(series, markers);
    }

    chart.timeScale().fitContent();

    return () => {
      chart.remove();
    };
  }, [container, data, markers, priceLines, lineStyle]);

  return (
    <div className="h-[420px] w-full overflow-hidden rounded-md">
      <div ref={setContainer} className="h-full w-full" />
    </div>
  );
}

export function TradeKlineModal({
  open,
  onOpenChange,
  symbol,
  name,
  trades,
  stat,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  symbol: string;
  name?: string | null;
  /** 该标的在回放范围内的全部交易（单笔回放传 1 笔） */
  trades: BacktestTrade[];
  /** 选股分析行的聚合统计（单笔回放不传，显示单笔头部） */
  stat?: {
    n_trades: number;
    total_return: number | null;
    win_rate: number | null;
    best: number | null;
    worst: number | null;
  } | null;
}) {
  const single = stat == null ? (trades[0] ?? null) : null;
  // K 线数据请求 id：每次打开 / 换标的自增，作为 fetch 状态的重置 key
  //（setState 不直接放进 effect 体，避免 react-hooks/set-state-in-effect）
  const [fetchId, setFetchId] = useState(0);
  const [loaded, setLoaded] = useState<{ id: number; data: KlinePoint[] } | null>(
    null
  );
  const [failedId, setFailedId] = useState<number | null>(null);

  // 数据窗口：最早入场前 45 天 ~ 最晚出场后 20 天
  const entryDates = trades
    .map((t) => shortDate(t.entry_date))
    .filter(Boolean)
    .sort();
  const exitDates = trades
    .map((t) => shortDate(t.exit_date))
    .filter(Boolean)
    .sort();
  const rangeStart = entryDates[0] ? addDays(entryDates[0], -LEAD_DAYS) : "";
  const rangeEnd = exitDates[exitDates.length - 1]
    ? addDays(exitDates[exitDates.length - 1], TAIL_DAYS)
    : "";
  const rangeDays =
    rangeStart && rangeEnd
      ? Math.max(
          1,
          Math.ceil(
            (new Date(`${rangeEnd}T00:00:00Z`).getTime() -
              new Date(`${rangeStart}T00:00:00Z`).getTime()) /
              86400000
          ) + 1
        )
      : 0;

  useEffect(() => {
    if (!open || !symbol || rangeDays === 0) return;
    const id = fetchId;
    let cancelled = false;
    fetch(
      `/api/historical?symbol=${encodeURIComponent(symbol)}&days=${rangeDays}`
    )
      .then((r) =>
        r.ok ? r.json() : Promise.reject(new Error(String(r.status)))
      )
      .then((arr: HistoricalRow[]) => {
        if (cancelled) return;
        if (!Array.isArray(arr) || arr.length === 0) {
          setFailedId(id);
          return;
        }
        const points = arr
          .filter(
            (d) =>
              d.open != null &&
              d.high != null &&
              d.low != null &&
              d.close != null
          )
          .map((d) => ({
            time: d.date,
            open: d.open as number,
            high: d.high as number,
            low: d.low as number,
            close: d.close as number,
          }));
        if (points.length === 0) {
          setFailedId(id);
          return;
        }
        setLoaded({ id, data: points });
      })
      .catch(() => {
        if (!cancelled) setFailedId(id);
      });
    return () => {
      cancelled = true;
    };
  }, [open, symbol, rangeDays, fetchId]);

  // 当前请求周期的派生状态（请求 id 变化时自然回到加载态，无需 effect 重置）
  const data = loaded?.id === fetchId ? loaded.data : null;
  const failed = failedId === fetchId;

  function handleOpenChange(next: boolean) {
    if (next && !open) setFetchId((i) => i + 1);
    onOpenChange(next);
  }

  const markers = buildMarkers(trades);
  // 首末笔区间交叠（首笔卖出晚于次笔买入）时省略区间价格线：多区间点线会连成一片
  const overlappingRanges = trades.some(
    (t, i) =>
      i > 0 &&
      shortDate(t.entry_date) !== "" &&
      shortDate(trades[i - 1]?.exit_date) !== "" &&
      shortDate(t.entry_date) <= shortDate(trades[i - 1]?.exit_date)
  );
  const showPriceLines = stat != null || !overlappingRanges;
  const priceLineStyle =
    stat != null ? SYMBOL_LINE_STYLE : HOLDING_LINE_STYLE;
  const priceLines: PriceLine[] = [];
  if (showPriceLines) {
    for (const t of trades) {
      if (t.entry_price != null) {
        priceLines.push({
          price: t.entry_price,
          title: `买 ${fmtNum(t.entry_price)}`,
          color: "#f0556b",
        });
      }
      if (t.exit_price != null) {
        priceLines.push({
          price: t.exit_price,
          title: `卖 ${fmtNum(t.exit_price)}`,
          color: "#20cd8d",
        });
      }
    }
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="sm:max-w-4xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            {name ?? symbol}
            <Badge variant="secondary">{symbol}</Badge>
            {stat ? (
              <Badge variant="outline">标的回放 · {trades.length} 笔</Badge>
            ) : (
              <Badge variant="outline">交易回放</Badge>
            )}
            {single?.exit_reason && (
              <Badge variant="outline">
                {exitReasonLabel(single.exit_reason)}
              </Badge>
            )}
          </DialogTitle>
          <DialogDescription>
            {single
              ? `${shortDate(single.entry_date)} 买入 → ${shortDate(
                  single.exit_date
                )} 卖出${
                  single.hold_days != null
                    ? ` · 持仓 ${single.hold_days} 天`
                    : ""
                }`
              : `${entryDates[0] ?? "—"} ~ ${
                  exitDates[exitDates.length - 1] ?? "—"
                } · 同日同方向多笔合并显示`}
          </DialogDescription>
        </DialogHeader>

        {single && (
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <Badge variant="outline" className="tabular-nums">
              买 {fmtNum(single.entry_price)} → 卖 {fmtNum(single.exit_price)}
            </Badge>
            <Badge
              variant="outline"
              className="tabular-nums"
              style={pnlStyle(single.pnl ?? single.ret)}
            >
              盈亏 {fmtMoney(single.pnl)} / {fmtPct(single.ret)}
            </Badge>
          </div>
        )}
        {stat && (
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <Badge
              variant="outline"
              className="tabular-nums"
              style={pnlStyle(stat.total_return)}
            >
              总收益 {fmtPct(stat.total_return)}
            </Badge>
            <Badge variant="outline" className="tabular-nums">
              胜率 {fmtPct(stat.win_rate)}
            </Badge>
            <Badge variant="outline" className="tabular-nums">
              最佳 / 最差{" "}
              <span style={pnlStyle(stat.best)}>{fmtPct(stat.best)}</span>
              {" / "}
              <span style={pnlStyle(stat.worst)}>{fmtPct(stat.worst)}</span>
            </Badge>
          </div>
        )}

        {failed ? (
          <EmptyState
            title="无 K 线数据"
            description="该区间无可用日 K 线，或行情服务暂不可用"
            compact
            className="h-[420px]"
          />
        ) : data == null ? (
          <Skeleton className="h-[420px] w-full" />
        ) : (
          <ReplayChart
            data={data}
            markers={markers}
            priceLines={priceLines}
            lineStyle={priceLineStyle}
          />
        )}
      </DialogContent>
    </Dialog>
  );
}
