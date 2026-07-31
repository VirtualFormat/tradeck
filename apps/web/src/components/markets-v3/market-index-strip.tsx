import { Card, CardContent } from "@/components/ui/card";
import { fmtDataDate, fmtPct, fmtPrice } from "@/lib/format";
import { getIndexHistorical } from "@/lib/openbb";
import { cn } from "@/lib/utils";

export interface MarketIndexDefinition {
  symbol: string;
  name: string;
}

interface MarketIndexStripProps {
  indices: MarketIndexDefinition[];
  date?: string;
  className?: string;
}

interface MarketIndexQuote extends MarketIndexDefinition {
  price: number | null;
  changePct: number | null;
  date: string | null;
}

function isoDate(date: Date): string {
  return date.toISOString().slice(0, 10);
}

async function fetchIndexQuote(
  index: MarketIndexDefinition,
  requestedDate?: string
): Promise<MarketIndexQuote> {
  const parsedEnd = requestedDate
    ? new Date(`${requestedDate}T00:00:00.000Z`)
    : new Date();
  const end = Number.isNaN(parsedEnd.getTime()) ? new Date() : parsedEnd;
  const start = new Date(end.getTime() - 14 * 24 * 60 * 60 * 1000);

  try {
    const rows = await getIndexHistorical(
      index.symbol,
      isoDate(start),
      isoDate(end)
    );
    if (rows.length === 0) {
      return { ...index, price: null, changePct: null, date: null };
    }

    const last = rows.at(-1)!;
    const previous = rows.at(-2) ?? last;
    return {
      ...index,
      price: last.close,
      changePct:
        previous.close > 0 ? (last.close - previous.close) / previous.close : 0,
      date: last.date,
    };
  } catch (error) {
    console.warn(`MarketIndexStrip ${index.symbol} failed:`, error);
    return { ...index, price: null, changePct: null, date: null };
  }
}

function IndexTile({ quote }: { quote: MarketIndexQuote }) {
  const changeClass =
    quote.changePct == null || quote.changePct === 0
      ? "text-muted-foreground"
      : quote.changePct > 0
        ? "text-up"
        : "text-down";

  return (
    <Card size="sm" className="h-full min-h-[92px] gap-0 py-3">
      <CardContent className="flex h-full min-w-0 flex-col px-3">
        <div className="flex min-w-0 items-start justify-between gap-2">
          <span className="min-w-0 truncate text-xs font-medium text-foreground">
            {quote.name}
          </span>
          <span className="shrink-0 text-[10px] text-muted-foreground tabular-nums">
            {fmtDataDate(quote.date) ?? "等待数据"}
          </span>
        </div>
        <span className="mt-2 text-lg leading-6 font-semibold text-foreground tabular-nums">
          {fmtPrice(quote.price)}
        </span>
        <span
          className={cn(
            "mt-auto text-xs leading-4 font-medium tabular-nums",
            changeClass
          )}
        >
          {fmtPct(quote.changePct)}
        </span>
      </CardContent>
    </Card>
  );
}

/**
 * 市场页指数带。
 * 手机为可横滑定宽卡，桌面改为等分网格；缺数据仍保留卡位。
 */
export async function MarketIndexStrip({
  indices,
  date,
  className,
}: MarketIndexStripProps) {
  const quotes = await Promise.all(
    indices.map((index) => fetchIndexQuote(index, date))
  );

  return (
    <section aria-label="主要指数" className={cn("min-w-0", className)}>
      <div className="-mx-3 overflow-x-auto px-3 pb-1 [scrollbar-width:none] sm:-mx-4 sm:px-4 lg:mx-0 lg:overflow-visible lg:px-0 [&::-webkit-scrollbar]:hidden">
        <div
          className={cn(
            "flex min-w-max gap-2.5 lg:grid lg:min-w-0",
            indices.length === 1 && "lg:grid-cols-1",
            indices.length === 2 && "lg:grid-cols-2",
            indices.length === 3 && "lg:grid-cols-3",
            indices.length >= 4 && "lg:grid-cols-4"
          )}
        >
          {quotes.map((quote) => (
            <div
              key={quote.symbol}
              className="w-[152px] shrink-0 sm:w-[160px] lg:w-auto"
            >
              <IndexTile quote={quote} />
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
