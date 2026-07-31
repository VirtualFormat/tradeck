import { normalizeSymbol } from "@/lib/utils";

export const WATCHLIST_KEY = "tradeck-watchlist";

export interface WatchlistQuote {
  symbol: string;
}

export function normalizeWatchlistSymbol(input: string): string {
  return normalizeSymbol(input).trim().toUpperCase();
}

export function parseWatchlist(value: string | null): string[] {
  if (!value) return [];
  try {
    const parsed: unknown = JSON.parse(value);
    if (!Array.isArray(parsed)) return [];
    return Array.from(
      new Set(
        parsed
          .filter((item): item is string => typeof item === "string")
          .map(normalizeWatchlistSymbol)
          .filter(Boolean)
      )
    );
  } catch {
    return [];
  }
}

export function reconcileWatchlist(
  requested: string[],
  validSymbols: WatchlistQuote[]
): string[] {
  const valid = new Set(validSymbols.map((item) => item.symbol));
  return requested.filter((symbol) => valid.has(symbol));
}

export async function validateWatchlistSymbols(
  symbols: string[]
): Promise<WatchlistQuote[]> {
  if (symbols.length === 0) return [];
  const response = await fetch(
    `/api/search/validate?symbols=${encodeURIComponent(symbols.join(","))}`,
    { cache: "no-store" }
  );
  if (!response.ok) {
    throw new Error("symbol validation failed");
  }
  const data: unknown = await response.json();
  return Array.isArray(data) ? (data as WatchlistQuote[]) : [];
}

export async function fetchValidQuotes<T extends WatchlistQuote>(
  symbols: string[]
): Promise<T[]> {
  if (symbols.length === 0) return [];
  const response = await fetch(
    `/api/quotes?symbols=${encodeURIComponent(symbols.join(","))}&_t=${Date.now()}`,
    { cache: "no-store" }
  );
  if (!response.ok) return [];
  const data: unknown = await response.json();
  return Array.isArray(data) ? (data as T[]) : [];
}

export async function validateWatchlistSymbol(
  input: string
): Promise<{ symbol: string; valid: boolean }> {
  const symbol = normalizeWatchlistSymbol(input);
  if (!symbol) return { symbol, valid: false };

  const validSymbols = await validateWatchlistSymbols([symbol]);
  return {
    symbol,
    valid: validSymbols.some((item) => item.symbol === symbol),
  };
}
