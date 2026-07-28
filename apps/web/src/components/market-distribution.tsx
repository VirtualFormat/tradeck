/**
 * 市场分布占比（首页用）
 * 获取全球大盘指数行情，按市场（US/HK/CN）统计数量分布
 * 渲染在 shadcn Card 内的 MarketPieChart（PieChart）
 */
import {
  getIndexHistorical,
  getEquityHistorical,
} from "@/lib/openbb";
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { MarketPieChart } from "@/components/market-pie-chart";
import { fmtDataDate } from "@/lib/format";

// 全球大盘指数 watchlist（与 market-overview 保持一致）
const ALL_INDICES = [
  { symbol: "^GSPC", name: "标普500", market: "us", type: "index" as const },
  { symbol: "^IXIC", name: "纳斯达克", market: "us", type: "index" as const },
  { symbol: "^DJI", name: "道琼斯", market: "us", type: "index" as const },
  { symbol: "^HSI", name: "恒生指数", market: "hk", type: "index" as const },
  { symbol: "^HSCEI", name: "恒生国企", market: "hk", type: "index" as const },
  { symbol: "000001.SS", name: "上证指数", market: "cn", type: "index" as const },
  { symbol: "399001.SZ", name: "深证成指", market: "cn", type: "index" as const },
  { symbol: "399006.SZ", name: "创业板指", market: "cn", type: "index" as const },
] as const;

const MARKET_LABEL: Record<string, string> = {
  us: "美股",
  hk: "港股",
  cn: "A股",
};

/** 返回该指数近 7 日最新交易日日期（无数据返回 null） */
async function fetchIndexLatestDate(
  symbol: string,
  type: "index" | "equity"
): Promise<string | null> {
  const end = new Date();
  const start = new Date(end.getTime() - 7 * 24 * 60 * 60 * 1000);
  const fmt = (d: Date) => d.toISOString().slice(0, 10);

  try {
    const hist =
      type === "index"
        ? await getIndexHistorical(symbol, fmt(start), fmt(end))
        : await getEquityHistorical(symbol, fmt(start), fmt(end));
    return hist.length > 0 ? hist[hist.length - 1].date : null;
  } catch {
    return null;
  }
}

async function fetchMarketDistribution(): Promise<{
  distribution: { name: string; value: number }[];
  latestDate: string | null;
}> {
  const results = await Promise.all(
    ALL_INDICES.map(async (idx) => ({
      market: idx.market,
      latestDate: await fetchIndexLatestDate(idx.symbol, idx.type),
    }))
  );

  const counts = new Map<string, number>();
  for (const r of results) {
    if (!r.latestDate) continue;
    counts.set(r.market, (counts.get(r.market) ?? 0) + 1);
  }

  // 全指数中最新的交易日
  const latestDate =
    results
      .map((r) => r.latestDate)
      .filter((d): d is string => Boolean(d))
      .sort()
      .pop() ?? null;

  // 按市场顺序输出，过滤掉没有数据的
  const distribution = ["us", "hk", "cn"]
    .map((m) => ({
      name: MARKET_LABEL[m] ?? m,
      value: counts.get(m) ?? 0,
    }))
    .filter((d) => d.value > 0);

  return { distribution, latestDate };
}

export async function MarketDistribution() {
  const { distribution, latestDate } = await fetchMarketDistribution();
  const dateLabel = fmtDataDate(latestDate);

  const total = distribution.reduce((sum, d) => sum + d.value, 0);

  return (
    <Card className="@container/card">
      <CardHeader>
        <CardTitle>市场分布</CardTitle>
        <CardDescription>
          全球大盘指数覆盖（共 {total} 只）
        </CardDescription>
        {dateLabel && (
          <CardAction className="text-xs text-muted-foreground">
            {dateLabel}
          </CardAction>
        )}
      </CardHeader>
      <CardContent className="pt-2">
        <MarketPieChart data={distribution} />
      </CardContent>
    </Card>
  );
}
