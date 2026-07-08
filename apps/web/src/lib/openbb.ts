/**
 * API 客户端
 * - 阶段 1 已迁移到 backend（quotes/historical/indices）：< 50ms
 * - 阶段 2 待迁移（movers/news/macro/commodities/treasury/profile/metrics/income）：直连 OpenBB
 */

// Backend API（从 DB 读，< 50ms）
const BACKEND_API_URL =
  process.env.BACKEND_API_URL ?? "http://localhost:8080";

// OpenBB API（阶段 1 暂保留给未迁移的组件）
const OPENBB_API_URL =
  process.env.OPENBB_API_URL ?? "http://localhost:6900";

export { OPENBB_API_URL };

const BACKEND = BACKEND_API_URL;
const OPENBB_BASE = `${OPENBB_API_URL}/api/v1`;

/** 按数据类型的缓存时间（秒）— 仅用于 OpenBB 调用 */
const CACHE = {
  quote: 30,
  historical: 300,
  discovery: 300,
  profile: 3600,
  fundamental: 3600,
  macro: 3600,
} as const;

export interface EquityQuote {
  symbol: string;
  name: string | null;
  last_price: number | null;
  change: number | null;
  change_percent: number | null;
  currency: string | null;
  volume: number | null;
  open: number | null;
  high: number | null;
  low: number | null;
  prev_close: number | null;
  exchange: string | null;
}

export interface HistoricalPrice {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface OpenBBResponse<T> {
  results: T[];
  warnings?: { message: string }[];
}

// ─── Backend API（从 DB 读，< 50ms） ──────────────────────

async function backendFetch<T>(path: string): Promise<T> {
  const url = `${BACKEND}${path}`;
  try {
    const res = await fetch(url, {
      headers: { Accept: "application/json" },
    });
    if (!res.ok) {
      console.warn(`backend ${path} failed: ${res.status}`);
      return [] as unknown as T;
    }
    const text = await res.text();
    if (!text) return [] as unknown as T;
    return JSON.parse(text) as T;
  } catch (err) {
    console.warn(`backend ${path} error:`, err);
    return [] as unknown as T;
  }
}

// ─── OpenBB API（阶段 1 暂保留，阶段 2 迁移） ──────────────

const memCache = new Map<string, { data: unknown; ts: number }>();

export async function fetchJSON<T>(
  path: string,
  init?: RequestInit,
  revalidate: number = CACHE.quote
): Promise<T> {
  const url = `${OPENBB_BASE}${path}`;
  const cached = memCache.get(url);
  if (cached && Date.now() - cached.ts < revalidate * 1000) {
    return cached.data as T;
  }
  try {
    const res = (await Promise.race([
      fetch(url, {
        ...init,
        cache: "no-store",
        headers: { Accept: "application/json", ...init?.headers },
      }),
      new Promise<null>((resolve) => setTimeout(() => resolve(null), 5000)),
    ])) as Response | null;

    if (!res) {
      console.warn(`OpenBB ${path} timeout (5s), returning empty`);
      if (cached) return cached.data as T;
      return { results: [] } as unknown as T;
    }
    if (!res.ok) {
      throw new Error(`OpenBB API ${path} failed: ${res.status}`);
    }
    const text = await res.text();
    let data: T;
    if (!text) {
      data = { results: [] } as unknown as T;
    } else {
      try {
        data = JSON.parse(text) as T;
      } catch {
        data = { results: [] } as unknown as T;
      }
    }
    memCache.set(url, { data, ts: Date.now() });
    return data;
  } catch (err) {
    if (err instanceof Error && (err.message.includes("ECONNRESET") || err.message.includes("fetch failed"))) {
      console.warn(`OpenBB ${path} reset, returning empty`);
      if (cached) return cached.data as T;
      return { results: [] } as unknown as T;
    }
    throw err;
  }
}

// ─── 已迁移到 backend 的 API ─────────────────────────────

export async function getEquityQuote(
  symbol: string
): Promise<EquityQuote | null> {
  const quotes = await backendFetch<EquityQuote[]>(
    `/api/quotes?symbols=${encodeURIComponent(symbol)}`
  );
  return quotes[0] ?? null;
}

export async function getEquityQuotes(
  symbols: string[]
): Promise<EquityQuote[]> {
  return backendFetch<EquityQuote[]>(
    `/api/quotes?symbols=${encodeURIComponent(symbols.join(","))}`
  );
}

export async function getEquityHistorical(
  symbol: string,
  startDate: string,
  endDate: string
): Promise<HistoricalPrice[]> {
  return backendFetch<HistoricalPrice[]>(
    `/api/historical?symbol=${encodeURIComponent(
      symbol
    )}&start_date=${startDate}&end_date=${endDate}`
  );
}

export async function getIndexHistorical(
  symbol: string,
  startDate: string,
  endDate: string
): Promise<HistoricalPrice[]> {
  return backendFetch<HistoricalPrice[]>(
    `/api/indices?symbol=${encodeURIComponent(
      symbol
    )}&start_date=${startDate}&end_date=${endDate}`
  );
}

// ─── 阶段 2 待迁移（暂保留直连 OpenBB） ────────────────────

function pickProvider(symbol: string): string {
  const sym = symbol.toUpperCase();
  if (sym.endsWith(".SS") || sym.endsWith(".SZ") || sym.endsWith(".BJ")) {
    return "akshare";
  }
  return "yfinance";
}

export interface EquityProfile {
  symbol: string;
  name: string | null;
  sector: string | null;
  industry: string | null;
  market_cap: number | null;
  currency: string | null;
  exchange: string | null;
  description: string | null;
  ceo: string | null;
  employees: number | null;
  website: string | null;
}

export interface FundamentalMetrics {
  symbol: string;
  market_cap: number | null;
  pe_ratio: number | null;
  forward_pe: number | null;
  peg_ratio: number | null;
  enterprise_to_ebitda: number | null;
  earnings_growth: number | null;
  revenue_growth: number | null;
  dividend_yield: number | null;
  beta: number | null;
  profit_margins: number | null;
  return_on_equity: number | null;
  debt_to_equity: number | null;
  current_ratio: number | null;
}

export interface IncomeStatement {
  fiscal_year: number | null;
  total_revenue: number | null;
  net_income: number | null;
  gross_profit: number | null;
  operating_income: number | null;
  research_and_development: number | null;
  ebitda: number | null;
}

export async function getEquityProfile(
  symbol: string
): Promise<EquityProfile | null> {
  const data = await fetchJSON<OpenBBResponse<EquityProfile>>(
    `/equity/profile?provider=yfinance&symbol=${encodeURIComponent(symbol)}`,
    undefined,
    CACHE.profile
  );
  return data.results[0] ?? null;
}

export async function getFundamentalMetrics(
  symbol: string
): Promise<FundamentalMetrics | null> {
  const data = await fetchJSON<OpenBBResponse<FundamentalMetrics>>(
    `/equity/fundamental/metrics?provider=yfinance&symbol=${encodeURIComponent(symbol)}`,
    undefined,
    CACHE.fundamental
  );
  return data.results[0] ?? null;
}

export async function getIncomeStatements(
  symbol: string,
  provider: string = "sec",
  period: string = "annual",
  limit: number = 3
): Promise<IncomeStatement[]> {
  const data = await fetchJSON<OpenBBResponse<IncomeStatement>>(
    `/equity/fundamental/income?provider=${provider}&symbol=${encodeURIComponent(
      symbol
    )}&period=${period}&limit=${limit}`,
    undefined,
    CACHE.fundamental
  );
  return data.results;
}

// ─── 新闻 ──────────────────────────────────────────────────

export interface NewsArticle {
  symbol: string;
  title: string;
  url: string;
  text: string | null;
  summary: string | null;
  publisher: string | null;
  date: string | null;
  source: string | null;
  symbols: string | null;
}

export async function getCompanyNews(
  symbol: string,
  limit: number = 20
): Promise<NewsArticle[]> {
  const data = await fetchJSON<OpenBBResponse<NewsArticle>>(
    `/news/company?provider=yfinance&symbol=${encodeURIComponent(
      symbol
    )}&limit=${limit}`,
    undefined,
    CACHE.historical
  );
  return data.results;
}

export async function getAggregatedNews(
  symbols: string[],
  perSymbol: number = 5
): Promise<NewsArticle[]> {
  const results = await Promise.all(
    symbols.map((s) => getCompanyNews(s, perSymbol).catch(() => []))
  );
  const merged = results.flat();
  merged.sort((a, b) => {
    const da = a.date ? new Date(a.date).getTime() : 0;
    const db = b.date ? new Date(b.date).getTime() : 0;
    return db - da;
  });
  return merged;
}

// ─── 宏观数据 ──────────────────────────────────────────────

export interface MacroSeries {
  date: string;
  value: number;
  country?: string;
}

export interface RateSeries {
  date: string;
  rate: number;
}

export async function getCPI(
  provider: string = "oecd",
  limit: number = 12
): Promise<MacroSeries[]> {
  const data = await fetchJSON<OpenBBResponse<MacroSeries>>(
    `/economy/cpi?provider=${provider}&limit=${limit}`,
    undefined,
    CACHE.macro
  );
  return data.results;
}

export async function getUnemployment(
  provider: string = "oecd",
  limit: number = 12
): Promise<MacroSeries[]> {
  const data = await fetchJSON<OpenBBResponse<MacroSeries>>(
    `/economy/unemployment?provider=${provider}&limit=${limit}`,
    undefined,
    CACHE.macro
  );
  return data.results;
}

export async function getGDPNominal(
  provider: string = "oecd",
  limit: number = 20
): Promise<MacroSeries[]> {
  const data = await fetchJSON<OpenBBResponse<MacroSeries>>(
    `/economy/gdp/nominal?provider=${provider}&limit=${limit}`,
    undefined,
    CACHE.macro
  );
  return data.results;
}

export async function getEFFR(
  provider: string = "federal_reserve",
  limit: number = 12
): Promise<RateSeries[]> {
  const data = await fetchJSON<OpenBBResponse<RateSeries>>(
    `/fixedincome/rate/effr?provider=${provider}&limit=${limit}`,
    undefined,
    CACHE.macro
  );
  return data.results.map((r) => ({ date: r.date, rate: r.rate }));
}

export async function getSOFR(
  provider: string = "federal_reserve",
  limit: number = 12
): Promise<RateSeries[]> {
  const data = await fetchJSON<OpenBBResponse<RateSeries>>(
    `/fixedincome/rate/sofr?provider=${provider}&limit=${limit}`,
    undefined,
    CACHE.macro
  );
  return data.results.map((r) => ({ date: r.date, rate: r.rate }));
}
