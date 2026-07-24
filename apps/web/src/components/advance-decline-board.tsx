/**
 * 涨跌平看板（US/HK/CN 三市场 Donut PieChart）
 * 服务端 async 组件：用 getEquityQuotes 拉各市场代表股列表，统计涨/跌/平数量
 * 渲染 3 张 shadcn Card，每张内嵌 AdvanceDeclineChart
 */
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { getEquityQuotes } from "@/lib/openbb";
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

// A 股代表列表（按市值选）
const CN_STOCKS = [
  "600519.SS", "601318.SS", "600036.SS", "000858.SZ",
  "002594.SZ", "300750.SZ", "601012.SS", "600900.SS",
  "000001.SZ", "601166.SS", "600276.SS", "601398.SS",
];

// 港股代表列表
const HK_STOCKS = [
  "0700.HK", "9988.HK", "0005.HK", "1299.HK",
  "0883.HK", "0939.HK", "0388.HK", "2318.HK",
  "0941.HK", "1810.HK", "3690.HK", "9618.HK",
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
): Promise<{ market: MarketDef; data: AdvanceDeclineData }> {
  try {
    const quotes = await getEquityQuotes(market.symbols);
    return { market, data: countAdvanceDecline(quotes) };
  } catch {
    return { market, data: { up: 0, down: 0, flat: 0 } };
  }
}

export async function AdvanceDeclineBoard() {
  const results = await Promise.all(MARKETS.map(fetchMarketData));

  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
      {results.map(({ market, data }) => {
        const total = data.up + data.down + data.flat;
        // 涨跌比：涨 / (涨+跌)，用于描述行
        const advDec =
          data.up + data.down > 0
            ? (data.up / (data.up + data.down)).toFixed(2)
            : "—";
        return (
          <Card
            key={market.key}
            size="sm"
            className="@container/card bg-linear-to-t from-primary/5 to-card shadow-xs dark:bg-card"
          >
            <CardHeader>
              <CardTitle className="text-base font-medium text-fg-dim">
                {market.label} 涨跌平
              </CardTitle>
              <CardDescription>
                <span className="hidden @[540px]/card:block">
                  样本 {total} 只 · 涨跌比 {advDec}
                </span>
                <span className="@[540px]/card:hidden">
                  {total} 只 · A/D {advDec}
                </span>
              </CardDescription>
            </CardHeader>
            <CardContent className="px-2 pt-2 sm:px-4 sm:pt-4">
              <AdvanceDeclineChart data={data} />
            </CardContent>
          </Card>
        );
      })}
    </div>
  );
}
