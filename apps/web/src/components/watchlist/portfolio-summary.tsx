import { EmptyState } from "@/components/empty-state";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { cn } from "@/lib/utils";

import {
  currencyPrefix,
  getQuoteFreshness,
  inferInstrumentIdentity,
  type NativeCurrency,
  type PortfolioSummaryProps,
  type PositionSummary,
  type WorkbenchMarket,
} from "./types";

const CURRENCY_ORDER: NativeCurrency[] = ["CNY", "HKD", "USD"];

function isFiniteNumber(value: number | null | undefined): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function formatMoney(value: number | null, currency: NativeCurrency): string {
  if (!isFiniteNumber(value)) return "待定价";
  return `${currencyPrefix(currency)}${value.toLocaleString("zh-CN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

function formatPercent(value: number | null): string {
  if (!isFiniteNumber(value)) return "待定价";
  return `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;
}

export function calculatePositionSummaries({
  items,
  quotes,
  now,
}: PortfolioSummaryProps): PositionSummary[] {
  const quoteBySymbol = new Map(
    quotes.map((quote) => [quote.symbol.trim().toUpperCase(), quote])
  );
  const buckets = new Map<
    NativeCurrency,
    {
      market: WorkbenchMarket;
      positionCount: number;
      pricedPositionCount: number;
      stalePositionCount: number;
      costBasis: number;
      marketValue: number;
    }
  >();

  for (const item of items) {
    if (!isFiniteNumber(item.quantity) || item.quantity <= 0) continue;
    if (!isFiniteNumber(item.averageCost) || item.averageCost < 0) continue;

    const { market, currency } = inferInstrumentIdentity(item.symbol);
    const current = buckets.get(currency) ?? {
      market,
      positionCount: 0,
      pricedPositionCount: 0,
      stalePositionCount: 0,
      costBasis: 0,
      marketValue: 0,
    };
    const quote = quoteBySymbol.get(item.symbol.trim().toUpperCase());

    current.positionCount += 1;
    current.costBasis += item.quantity * item.averageCost;
    const quotePrice =
      quote && isFiniteNumber(quote.price) && quote.price >= 0
        ? quote.price
        : null;
    const freshness = getQuoteFreshness(
      item.symbol,
      quote?.dataAsOf ?? null,
      now
    );
    if (quotePrice !== null && !freshness.isStale) {
      current.pricedPositionCount += 1;
      current.marketValue += item.quantity * quotePrice;
    } else if (quotePrice !== null && freshness.isStale) {
      current.stalePositionCount += 1;
    }
    buckets.set(currency, current);
  }

  return CURRENCY_ORDER.flatMap((currency) => {
    const bucket = buckets.get(currency);
    if (!bucket) return [];

    const fullyPriced = bucket.pricedPositionCount === bucket.positionCount;
    const marketValue = fullyPriced ? bucket.marketValue : null;
    const unrealizedPnl =
      marketValue === null ? null : marketValue - bucket.costBasis;
    const returnPercent =
      unrealizedPnl === null || bucket.costBasis <= 0
        ? null
        : (unrealizedPnl / bucket.costBasis) * 100;

    return [
      {
        market: bucket.market,
        currency,
        positionCount: bucket.positionCount,
        pricedPositionCount: bucket.pricedPositionCount,
        stalePositionCount: bucket.stalePositionCount,
        marketValue,
        costBasis: bucket.costBasis,
        unrealizedPnl,
        returnPercent,
      },
    ];
  });
}

export function PortfolioSummary(props: PortfolioSummaryProps) {
  const summaries = calculatePositionSummaries(props);

  if (summaries.length === 0) {
    return (
      <EmptyState
        title="暂无持仓"
        description="为自选标的录入数量和成本后，这里会按原生币种核算。"
      />
    );
  }

  return (
    <Card size="sm">
      <CardHeader className="border-b">
        <CardTitle>持仓摘要</CardTitle>
        <CardDescription>
          USD、CNY 与 HKD 独立核算，不进行跨币种合计。
        </CardDescription>
      </CardHeader>
      <CardContent className="px-0">
        <div className="divide-y">
          {summaries.map((summary) => {
            const pnlClass =
              summary.unrealizedPnl === null
                ? "text-muted-foreground"
                : summary.unrealizedPnl >= 0
                  ? "text-up"
                  : "text-down";

            return (
              <div
                key={summary.currency}
                className="grid gap-3 px-4 py-3 sm:grid-cols-[7rem_repeat(4,minmax(0,1fr))] sm:items-center"
              >
                <div className="flex items-center gap-2">
                  <Badge variant="secondary">{summary.currency}</Badge>
                  <span className="text-xs text-muted-foreground">
                    {summary.positionCount} 笔
                  </span>
                </div>
                <div>
                  <div className="text-[11px] text-muted-foreground">市值</div>
                  <div className="mt-0.5 font-mono font-medium tabular-nums">
                    {formatMoney(summary.marketValue, summary.currency)}
                  </div>
                </div>
                <div>
                  <div className="text-[11px] text-muted-foreground">成本</div>
                  <div className="mt-0.5 font-mono font-medium tabular-nums">
                    {formatMoney(summary.costBasis, summary.currency)}
                  </div>
                </div>
                <div>
                  <div className="text-[11px] text-muted-foreground">
                    浮盈亏
                  </div>
                  <div
                    className={cn(
                      "mt-0.5 font-mono font-medium tabular-nums",
                      pnlClass
                    )}
                  >
                    {formatMoney(summary.unrealizedPnl, summary.currency)}
                  </div>
                </div>
                <div>
                  <div className="text-[11px] text-muted-foreground">收益率</div>
                  <div
                    className={cn(
                      "mt-0.5 font-mono font-medium tabular-nums",
                      pnlClass
                    )}
                  >
                    {formatPercent(summary.returnPercent)}
                  </div>
                  <div
                    className={cn(
                      "mt-0.5 text-[10px]",
                      summary.pricedPositionCount < summary.positionCount
                        ? "text-warn"
                        : "text-muted-foreground"
                    )}
                  >
                    {summary.pricedPositionCount}/{summary.positionCount} 笔有效报价
                  </div>
                  {summary.pricedPositionCount < summary.positionCount ? (
                    <div className="mt-0.5 text-[10px] text-warn">
                      {summary.stalePositionCount > 0
                        ? `含 ${summary.stalePositionCount} 笔旧价；市值与盈亏暂停核算`
                        : "报价缺失；市值与盈亏暂停核算"}
                    </div>
                  ) : null}
                </div>
              </div>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
}
