/**
 * 大盘指数总览组件（服务端）
 * - 数据：通过 backend API 拉指数/个股历史，取最新收盘价 + 近 30 日走势
 * - UI：
 *   - 顶部 shadcn Card + IndexAreaChart（多指数相对走势 AreaChart）
 *   - 下方 grid of IndexCard（shadcn Card + phosphor icons，替代文本箭头）
 * - 保留 block SectionCards 风格（grid 渐变背景）
 */
import {
  getIndexHistorical,
  getEquityHistorical,
  type HistoricalPrice,
} from "@/lib/openbb";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { IndexAreaChart, type IndexSeries } from "@/components/index-area-chart";
import { IndexCard, type IndexQuote } from "@/components/index-card";

// 全球大盘指数 watchlist（yfinance 代码）
const ALL_INDICES = [
  { symbol: "^GSPC", name: "标普500", market: "us", type: "index" as const },
  { symbol: "^IXIC", name: "纳斯达克", market: "us", type: "index" as const },
  { symbol: "^DJI", name: "道琼斯", market: "us", type: "index" as const },
  { symbol: "^HSI", name: "恒生指数", market: "hk", type: "index" as const },
  { symbol: "^HSCEI", name: "恒生国企", market: "hk", type: "index" as const },
  { symbol: "000001.SS", name: "上证指数", market: "cn", type: "equity" as const },
  { symbol: "399001.SZ", name: "深证成指", market: "cn", type: "equity" as const },
  { symbol: "399006.SZ", name: "创业板指", market: "cn", type: "equity" as const },
];

// AreaChart 配色（循环 chart-1..chart-5，shadcn preset）
const CHART_COLORS = [
  "var(--chart-1)",
  "var(--chart-2)",
  "var(--chart-3)",
  "var(--chart-4)",
  "var(--chart-5)",
];

// AreaChart 最多展示的指数数量（避免线条过密）
const MAX_CHART_SERIES = 4;

/** 把 symbol 转成合法的 CSS/JS 标识符（用于 dataKey 与 --color-KEY） */
function slugify(s: string): string {
  return s.replace(/[^a-zA-Z0-9_-]/g, "_");
}

// 拉近 30 个交易日历史，取最新 2 条算涨跌幅 + 整条序列传给卡片 mini chart
async function fetchIndexQuoteAndHist(
  symbol: string,
  type: "index" | "equity"
): Promise<{
  price: number | null;
  changePct: number | null;
  hist: { date: string; value: number }[];
}> {
  const end = new Date();
  const start = new Date(end.getTime() - 14 * 24 * 60 * 60 * 1000);
  const fmt = (d: Date) => d.toISOString().slice(0, 10);

  try {
    const hist =
      type === "index"
        ? await getIndexHistorical(symbol, fmt(start), fmt(end))
        : await getEquityHistorical(symbol, fmt(start), fmt(end));

    if (hist.length === 0) return { price: null, changePct: null, hist: [] };

    const last7 = hist.slice(-7);
    const last = last7[last7.length - 1];
    const prev = last7.length > 1 ? last7[last7.length - 2] : last;
    const changePct = prev.close > 0 ? (last.close - prev.close) / prev.close : 0;

    return {
      price: last.close,
      changePct,
      hist: last7.map((p) => ({ date: p.date, value: p.close })),
    };
  } catch (err) {
    console.error(`fetchIndexQuoteAndHist ${symbol} failed:`, err);
    return { price: null, changePct: null, hist: [] };
  }
}

async function fetchIndices(market: string = "global"): Promise<IndexQuote[]> {
  const indices =
    market === "global"
      ? ALL_INDICES
      : ALL_INDICES.filter((i) => i.market === market);

  const results = await Promise.all(
    indices.map(async (idx) => {
      const { price, changePct, hist } = await fetchIndexQuoteAndHist(
        idx.symbol,
        idx.type
      );
      return {
        symbol: idx.symbol,
        cnName: idx.name,
        market: idx.market,
        last_price: price,
        change_percent: changePct,
        currency: null,
        hist,
      } satisfies IndexQuote;
    })
  );
  return results;
}

/** 拉近 30 日原始历史（带日期，用于 AreaChart 归一化合并） */
async function fetchIndexHist30(
  symbol: string,
  type: "index" | "equity"
): Promise<HistoricalPrice[]> {
  const end = new Date();
  const start = new Date(end.getTime() - 14 * 24 * 60 * 60 * 1000);
  const fmt = (d: Date) => d.toISOString().slice(0, 10);

  try {
    const hist =
      type === "index"
        ? await getIndexHistorical(symbol, fmt(start), fmt(end))
        : await getEquityHistorical(symbol, fmt(start), fmt(end));
    return hist.slice(-7);
  } catch (err) {
    console.error(`fetchIndexHist30 ${symbol} failed:`, err);
    return [];
  }
}

/** 拉多指数 30 日历史，归一化为相对起点的涨跌幅（%），按日期合并 */
async function fetchIndexRelatives(
  list: typeof ALL_INDICES
): Promise<{ data: Array<Record<string, string | number | null>>; series: IndexSeries[] }> {
  const histList = await Promise.all(
    list.map(async (idx) => ({
      idx,
      hist: await fetchIndexHist30(idx.symbol, idx.type),
    }))
  );

  // 过滤掉没拿到历史的
  const valid = histList.filter((h) => h.hist.length > 0);

  const series: IndexSeries[] = valid.map((h, i) => ({
    key: slugify(h.idx.symbol),
    cnName: h.idx.name,
    color: CHART_COLORS[i % CHART_COLORS.length],
  }));

  // 收集所有日期并排序
  const allDates = new Set<string>();
  valid.forEach(({ hist }) => hist.forEach((p) => allDates.add(p.date)));
  const sortedDates = Array.from(allDates).sort();

  // 每个指数的起点 close（用于归一化）
  const firstClose = new Map<string, number>();
  valid.forEach(({ idx, hist }) => {
    const first = hist[0]?.close;
    if (first != null && first > 0) {
      firstClose.set(idx.symbol, first);
    }
  });

  // 按日期合并；缺失值用 null（AreaChart connectNulls 会跳过）
  const data: Array<Record<string, string | number | null>> = sortedDates.map(
    (date) => {
      const row: Record<string, string | number | null> = { date };
      valid.forEach(({ idx, hist }) => {
        const point = hist.find((p) => p.date === date);
        const first = firstClose.get(idx.symbol);
        if (point && first != null && first > 0) {
          row[slugify(idx.symbol)] =
            ((point.close - first) / first) * 100;
        } else {
          row[slugify(idx.symbol)] = null;
        }
      });
      return row;
    }
  );

  return { data, series };
}

export async function MarketOverview({ market = "global" }: { market?: string }) {
  const indices = await fetchIndices(market);

  if (indices.length === 0) {
    return (
      <Card className="flex h-48 items-center justify-center border border-border bg-panel text-muted ring-0">
        等待指数数据...
      </Card>
    );
  }

  // AreaChart 选前 N 个指数（避免线条过密）
  const filteredList =
    market === "global"
      ? ALL_INDICES.slice(0, MAX_CHART_SERIES)
      : ALL_INDICES.filter((i) => i.market === market).slice(
          0,
          MAX_CHART_SERIES
        );

  const { data: chartData, series: chartSeries } =
    await fetchIndexRelatives(filteredList);

  return (
    <div className="flex flex-col gap-4">
      {chartSeries.length > 0 && (
        <Card className="@container/card">
          <CardHeader>
            <CardTitle>近 30 日相对走势</CardTitle>
            <CardDescription>
              各指数相对 30 日前收盘的涨跌幅（%）
            </CardDescription>
          </CardHeader>
          <CardContent className="px-2 pt-4 sm:px-6 sm:pt-6">
            <IndexAreaChart data={chartData} series={chartSeries} />
          </CardContent>
        </Card>
      )}

      <div className="grid grid-cols-1 gap-4 *:data-[slot=card]:bg-linear-to-t *:data-[slot=card]:from-primary/5 *:data-[slot=card]:to-card *:data-[slot=card]:shadow-xs @xl/main:grid-cols-2 @5xl/main:grid-cols-4 dark:*:data-[slot=card]:bg-card">
        {indices.map((quote) => (
          <IndexCard key={quote.symbol} quote={quote} />
        ))}
      </div>
    </div>
  );
}
