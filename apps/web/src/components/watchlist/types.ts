import type { WatchlistGroup, WatchlistItem } from "@/lib/watchlist";

export type WorkbenchMarket = "CN" | "HK" | "US";
export type NativeCurrency = "CNY" | "HKD" | "USD";

export interface WorkbenchQuote {
  symbol: string;
  name: string | null;
  price: number | null;
  changePercent: number | null;
  volume: number | null;
  dataAsOf: string | null;
  fetchedAt: string | null;
}

export interface PositionSummary {
  market: WorkbenchMarket;
  currency: NativeCurrency;
  positionCount: number;
  pricedPositionCount: number;
  stalePositionCount: number;
  marketValue: number | null;
  costBasis: number;
  unrealizedPnl: number | null;
  returnPercent: number | null;
}

export interface QuoteFreshness {
  isStale: boolean;
  localDateLabel: string | null;
}

export interface PortfolioSummaryProps {
  items: WatchlistItem[];
  quotes: WorkbenchQuote[];
  now: Date;
}

export interface WatchlistTableProps {
  items: WatchlistItem[];
  groups: WatchlistGroup[];
  quotes: WorkbenchQuote[];
  now: Date;
  activeGroupId: string | null;
  onEdit: (item: WatchlistItem) => void;
  onRemove: (item: WatchlistItem) => void;
}

export function inferInstrumentIdentity(symbol: string): {
  market: WorkbenchMarket;
  currency: NativeCurrency;
} {
  const normalized = symbol.trim().toUpperCase();

  if (/\.(SH|SS|SZ|BJ)$/.test(normalized)) {
    return { market: "CN", currency: "CNY" };
  }
  if (normalized.endsWith(".HK")) {
    return { market: "HK", currency: "HKD" };
  }
  return { market: "US", currency: "USD" };
}

export function currencyPrefix(currency: NativeCurrency): string {
  if (currency === "CNY") return "CN¥";
  if (currency === "HKD") return "HK$";
  return "US$";
}

const WEEKDAY_STALE_MS = 36 * 60 * 60 * 1000;
const WEEKEND_STALE_MS = 72 * 60 * 60 * 1000;
const MARKET_TIME_ZONES: Record<WorkbenchMarket, string> = {
  CN: "Asia/Shanghai",
  HK: "Asia/Hong_Kong",
  US: "America/New_York",
};

function zonedDateParts(date: Date, timeZone: string) {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    weekday: "short",
  }).formatToParts(date);
  const value = (type: Intl.DateTimeFormatPartTypes) =>
    parts.find((part) => part.type === type)?.value ?? "";

  return {
    dateKey: `${value("year")}-${value("month")}-${value("day")}`,
    label: `${value("month")}-${value("day")}`,
    weekday: value("weekday"),
  };
}

export function getQuoteFreshness(
  symbol: string,
  dataAsOf: string | null | undefined,
  now: Date
): QuoteFreshness {
  if (!dataAsOf) return { isStale: true, localDateLabel: null };

  const updatedDate = new Date(dataAsOf);
  if (!Number.isFinite(updatedDate.getTime())) {
    return { isStale: true, localDateLabel: null };
  }

  const { market } = inferInstrumentIdentity(symbol);
  const timeZone = MARKET_TIME_ZONES[market];
  const quoteLocal = zonedDateParts(updatedDate, timeZone);
  const currentLocal = zonedDateParts(now, timeZone);
  const isWeekend =
    currentLocal.weekday === "Sat" || currentLocal.weekday === "Sun";
  const staleAfterMs = isWeekend ? WEEKEND_STALE_MS : WEEKDAY_STALE_MS;
  const ageMs = now.getTime() - updatedDate.getTime();

  return {
    isStale:
      ageMs < -5 * 60 * 1000 ||
      ageMs > staleAfterMs ||
      quoteLocal.dateKey > currentLocal.dateKey,
    localDateLabel: quoteLocal.label,
  };
}
