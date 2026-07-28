/**
 * 涨跌平看板（US/HK/CN 三市场，单张宽面板）
 * 服务端 async 组件：用 getEquityQuotes 拉各市场代表股列表，统计涨/跌/平数量
 * 一张 Card 内 grid 三列，每列一个 AdvanceDeclineChart（radial-stacked 半环）
 */
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { getEquityQuotes } from "@/lib/openbb";
import { fmtDataTime } from "@/lib/format";
import {
  AdvanceDeclineChart,
  type AdvanceDeclineData,
} from "@/components/advance-decline-chart";

// 美股代表列表（按市值选 30 只，覆盖科技/金融/消费/医疗/能源）
const US_STOCKS = [
  "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA",
  "BRK-B", "JPM", "V", "JNJ", "WMT", "PG", "MA", "UNH",
  "HD", "DIS", "BAC", "XOM", "KO", "PEP", "CSCO", "NFLX",
  "ADBE", "CRM", "INTC", "AMD", "ORCL", "TMO", "COST",
];

// A 股代表列表（按市值选；沪市用 .SH）
const CN_STOCKS = [
  "600519.SH", "601318.SH", "600036.SH", "000858.SZ",
  "002594.SZ", "300750.SZ", "601012.SH", "600900.SH",
  "000001.SZ", "601166.SH", "600276.SH", "601398.SH",
];

// 港股代表列表（5 位补零）
const HK_STOCKS = [
  "00700.HK", "09988.HK", "00005.HK", "01299.HK",
  "00883.HK", "00939.HK", "00388.HK", "02318.HK",
  "00941.HK", "01810.HK", "03690.HK", "09618.HK",
];

interface MarketDef {
  key: "us" | "hk" | "cn";
  label: string;
  symbols: string[];
}

const MARKETS: MarketDef[] = [
  { key: "us", label: "美股", symbols: US_STOCKS },
  { key: "hk", label: "港股", symbols: HK_STOCKS },
  { key: "cn", label: "A股", symbols: CN_STOCKS },
];

function countAdvanceDecline(
  quotes: Array<{ change_percent: number | null } | null | undefined>
): AdvanceDeclineData {
  let up = 0;
  let down = 0;
  let flat = 0;
  for (const q of quotes) {
    const pct = q?.change_percent;
    if (pct == null || !Number.isFinite(pct)) {
      // 缺数据不计入
      continue;
    }
    if (pct > 0) up += 1;
    else if (pct < 0) down += 1;
    else flat += 1;
  }
  return { up, down, flat };
}

async function fetchMarketData(
  market: MarketDef
): Promise<{
  market: MarketDef;
  data: AdvanceDeclineData;
  updatedAt: string | null;
}> {
  try {
    const quotes = await getEquityQuotes(market.symbols);
    // 取样本中最新的报价更新时间（盘中分钟级）
    const updatedAt =
      quotes
        .map((q) => q.updated_at)
        .filter((t): t is string => Boolean(t))
        .sort()
        .pop() ?? null;
    return { market, data: countAdvanceDecline(quotes), updatedAt };
  } catch {
    return { market, data: { up: 0, down: 0, flat: 0 }, updatedAt: null };
  }
}

export async function AdvanceDeclineBoard() {
  const results = await Promise.all(MARKETS.map(fetchMarketData));

  // 全市场样本中最新的报价时间，作为面板数据时点
  const latestUpdated = results
    .map((r) => r.updatedAt)
    .filter((t): t is string => Boolean(t))
    .sort()
    .pop();
  const timeLabel = fmtDataTime(latestUpdated);

  return (
    <Card
      size="sm"
      className="@container/card bg-linear-to-t from-primary/5 to-card shadow-xs dark:bg-card"
    >
      <CardHeader>
        <CardTitle className="text-base font-medium text-fg-dim">
          涨跌平
        </CardTitle>
        <CardDescription>各市场代表样本股的当日涨跌家数</CardDescription>
        {timeLabel && (
          <CardAction className="text-xs text-muted-foreground">
            {timeLabel}
          </CardAction>
        )}
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          {results.map(({ market, data }) => (
            <AdvanceDeclineChart
              key={market.key}
              label={market.label}
              data={data}
            />
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
